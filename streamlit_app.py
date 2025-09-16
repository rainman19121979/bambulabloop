import streamlit as st
import zipfile
import io
import datetime
import re
import math
from typing import Optional, Tuple

# ===== Exceptions, Limits & 3MF-Wrapper (required) =====
class GcodeParseError(Exception):
    """Raised when a 3MF does not contain readable G-code or structure is invalid."""
    pass

class GcodeSizeError(Exception):
    """Raised when the generated G-code exceeds a safe size limit."""
    pass

# Reasonable defaults
MAX_OUTPUT_GCODE_MB = 40          # Max size of generated G-code (MB)
MAX_LOOPS = 50                    # Safety limit
MAX_FILES = 20                    # Safety limit for multi-file combine
MAX_CUSTOM_SWEEP_KB = 64          # Max size of custom sweep (KB)

def wrap_in_3mf(new_gcode_text: str, base_3mf_file) -> bytes:
    """
    Take the uploaded .3mf, replace the FIRST .gcode inside with new_gcode_text,
    and return a fresh .3mf as bytes.
    """
    import zipfile, io

    with zipfile.ZipFile(base_3mf_file, "r") as zin:
        names = zin.namelist()
        gcode_names = [n for n in names if n.endswith(".gcode")]
        if not gcode_names:
            fname = getattr(base_3mf_file, "name", "uploaded.3mf")
            raise GcodeParseError(f"No .gcode asset found in {fname}")

        replace_target = gcode_names[0]

        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for n in names:
                if n == replace_target:
                    zout.writestr(n, new_gcode_text)
                else:
                    zout.writestr(n, zin.read(n))

        return out_buf.getvalue()


# ========== G-code Processing Functions
def get_sweep_pattern():
    """Returns the standard sweep pattern G-code."""
    return """
; --- AUTO SWEEP START ---
M400
G91
G1 Z5 F2000
G90
G1 X0 Y220 F6000
G1 X0 Y0 F6000
G1 X55 Y220 F6000
G1 X55 Y0 F6000
G1 X110 Y220 F6000
G1 X110 Y0 F6000
G1 X165 Y220 F6000
G1 X165 Y0 F6000
G1 X220 Y220 F6000
G1 X220 Y0 F6000
M400
; --- AUTO SWEEP END ---
"""


# ========== Combine Multiple Files ==========
def build_combined_gcode(three_mf_files, sweep_interval_min):
    sweep_interval_sec = sweep_interval_min * 60
    sweep = get_sweep_pattern()
    combined_gcode = "; === COMBINED FARM MODE GCODE START ===\n"

    for idx, uploaded_file in enumerate(three_mf_files):
        with zipfile.ZipFile(uploaded_file, "r") as zip_ref:
            gcode_files = [f for f in zip_ref.namelist() if f.endswith(".gcode")]
            if not gcode_files:
                raise ValueError(f"No G-code found inside {uploaded_file.name}. Slice it first in Bambu Studio.")
            gcode_name = gcode_files[0]
            gcode_text = zip_ref.read(gcode_name).decode("utf-8")

            header, print_moves, _ = find_gcode_sections(gcode_text)
            if idx == 0:  # Use header from first file
                combined_gcode = header

            combined_gcode += f"\n; === FILE {idx+1}: {uploaded_file.name} START ===\n"
            combined_gcode += print_moves
            combined_gcode += f"\n; === FILE {idx+1}: {uploaded_file.name} END ===\n"

            # Sweep + wait between jobs
            if idx < len(three_mf_files) - 1:
                combined_gcode += f"""
; --- AUTO SWEEP after file {idx+1} ---
M400
G4 S{sweep_interval_sec} ; wait {sweep_interval_min} minutes
{sweep}
"""

    # Final sweep + homing
    combined_gcode += f"""
; --- FINAL SWEEP ---
M400
{sweep}
G28 ; home all axes
; === COMBINED FARM MODE GCODE END ===
"""
    return combined_gcode


# ========== 3MF Handling ==========
def find_gcode_sections(gcode_text):
    """Find the header, print moves, and footer sections of G-code."""
    # Try to find print content using different possible markers
    start_markers = [
        ";LAYER:0",
        "; layer 0",
        ";TYPE:WALL-OUTER",
        "G1 Z0.3",  # First layer height
        "; retract extruder"  # Bamboo-specific marker
    ]
    
    end_markers = [
        ";END gcode",
        ";End of Gcode",
        ";end of print",
        "M104 S0",  # Turn off extruder
        "M140 S0"   # Turn off bed
    ]
    
    start = -1
    end = -1
    
    # Find start of actual print moves
    for marker in start_markers:
        pos = gcode_text.find(marker)
        if pos != -1:
            start = pos
            break
    
    # Find end of print moves
    for marker in end_markers:
        pos = gcode_text.rfind(marker)
        if pos != -1:
            end = pos
            break
    
    if start == -1 or end == -1:
        # If we can't find markers, try to find the first G1 move and last M104/M140
        lines = gcode_text.split('\n')
        for i, line in enumerate(lines):
            if start == -1 and ('G1' in line or 'G0' in line) and 'Z' in line:
                start = gcode_text.find(line)
            if ('M104 S0' in line or 'M140 S0' in line or 
                'G28' in line):  # Home command often indicates end
                end = gcode_text.find(line)
    
    if start == -1 or end == -1:
        st.error("Could not find print boundaries in G-code. Please make sure the file is properly sliced in Bambu Studio.")
        st.error("Debug Info:")
        st.code(gcode_text[:1000])  # Show first 1000 characters for debugging
        raise ValueError("Could not parse G-code structure")
        
    header = gcode_text[:start]
    print_moves = gcode_text[start:end]
    footer = gcode_text[end:]
    
    # Validate that we have reasonable content
    if len(print_moves) < 100:  # Too short to be valid print moves
        st.error("Print content seems too short. Please check if the file is properly sliced.")
        raise ValueError("Invalid print content length")
        
    return header, print_moves, footer

def safe_decode(data: bytes) -> str:
    """Try multiple decodings before failing."""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    raise UnicodeDecodeError("all", b"", 0, 1, "Unable to decode G-code bytes")

def extract_first_gcode_from_3mf(uploaded_file) -> Tuple[str, str]:
    """
    Returns (gcode_text, internal_path).
    Raises GcodeParseError if not found / unreadable.
    """
    try:
        with zipfile.ZipFile(uploaded_file, "r") as z:
            gcode_paths = [p for p in z.namelist() if p.endswith(".gcode")]
            if not gcode_paths:
                raise GcodeParseError(f"No .gcode asset found in {uploaded_file.name}")
            raw = z.read(gcode_paths[0])
            text = safe_decode(raw)
            return text, gcode_paths[0]
    except zipfile.BadZipFile:
        raise GcodeParseError(f"{uploaded_file.name} is not a valid 3MF (zip) file")
    except UnicodeDecodeError as ue:
        raise GcodeParseError(f"Encoding error in {uploaded_file.name}: {ue}")

def enforce_limits(num_loops: int, files_count: int, custom_sweep: str):
    if num_loops > MAX_LOOPS:
        raise ValueError(f"Loops exceed limit ({num_loops}>{MAX_LOOPS})")
    if files_count > MAX_FILES:
        raise ValueError(f"Too many files ({files_count}>{MAX_FILES})")
    if custom_sweep and (len(custom_sweep.encode('utf-8'))/1024) > MAX_CUSTOM_SWEEP_KB:
        raise ValueError(f"Custom sweep too large (> {MAX_CUSTOM_SWEEP_KB} KB)")

def approx_size_mb(s: str) -> float:
    return len(s.encode('utf-8')) / (1024*1024)

# --- Optimized: use list assembly instead of repeated += ---

def create_looped_gcode(gcode_text, num_loops, sweep_interval_min,
                        sweep_pattern_override=None, disable_final_home=False):
    sweep_interval_sec = sweep_interval_min * 60
    sweep = (sweep_pattern_override.strip() + "\n") if sweep_pattern_override and sweep_pattern_override.strip() else get_sweep_pattern()
    header, print_moves, footer = find_gcode_sections(gcode_text)

    parts = [header]
    for i in range(num_loops):
        parts.append(f"\n; === LOOP {i+1} START ===\n")
        parts.append(print_moves)
        parts.append(f"\n; === LOOP {i+1} END ===\n")
        if i < num_loops - 1:
            parts.append(
f"""\n; --- WAITING AND SWEEPING ---
M400
G4 S{sweep_interval_sec} ; wait {sweep_interval_min} minutes
{sweep}
""")
    parts.append("\n; --- FINAL SWEEP ---\n")
    parts.append(sweep)
    if not disable_final_home:
        parts.append("G28 ; home all axes\n")
    parts.append(footer)

    out = "".join(parts)
    if approx_size_mb(out) > MAX_OUTPUT_GCODE_MB:
        raise GcodeSizeError(f"Output G-code exceeds {MAX_OUTPUT_GCODE_MB} MB limit (try fewer loops)")
    return out

def build_combined_looped_gcode(three_mf_files, num_loops, sweep_interval_min,
                                sweep_between_files=True, per_file_wait_min=0,
                                sweep_pattern_override=None, disable_final_home=False):
    sweep_interval_sec = sweep_interval_min * 60
    per_file_wait_sec = per_file_wait_min * 60
    sweep = (sweep_pattern_override.strip() + "\n") if sweep_pattern_override and sweep_pattern_override.strip() else get_sweep_pattern()

    # Header from first file
    first_text, _ = extract_first_gcode_from_3mf(three_mf_files[0])
    header, _, _ = find_gcode_sections(first_text)

    base_parts = [header, "\n; === COMBINED FILES BASE SEQUENCE START ===\n"]
    for idx, uf in enumerate(three_mf_files):
        gtxt, _ = extract_first_gcode_from_3mf(uf)
        _, print_moves, _ = find_gcode_sections(gtxt)
        base_parts.append(f"\n; --- FILE {idx+1}: {uf.name} START ---\n")
        base_parts.append(print_moves)
        base_parts.append(f"\n; --- FILE {idx+1}: {uf.name} END ---\n")
        if idx < len(three_mf_files) - 1 and sweep_between_files:
            if per_file_wait_min > 0:
                base_parts.append(f"\n; WAIT BEFORE NEXT FILE\nG4 S{per_file_wait_sec} ; wait {per_file_wait_min} minutes\n")
            base_parts.append(f"\n; SWEEP BETWEEN FILES\n{sweep}")

    base_parts.append("\n; === COMBINED FILES BASE SEQUENCE END ===\n")
    combined_base = "".join(base_parts)

    loop_parts = ["; === MULTI-FILE LOOPED FARM MODE START ===\n"]
    for li in range(num_loops):
        loop_parts.append(f"\n; ===== LOOP {li+1} START =====\n")
        loop_parts.append(combined_base)
        loop_parts.append(f"\n; ===== LOOP {li+1} END =====\n")
        if li < num_loops - 1:
            loop_parts.append(
f"""\n; --- BETWEEN LOOP SEQUENCES ---
G4 S{sweep_interval_sec} ; wait {sweep_interval_min} minutes
{sweep}""")
    loop_parts.append(f"\n; FINAL SWEEP{' (NO HOME)' if disable_final_home else ' & HOME'}\n")
    loop_parts.append(sweep)
    if not disable_final_home:
        loop_parts.append("\nG28")
    loop_parts.append("\n; === MULTI-FILE LOOPED FARM MODE END ===\n")

    out = "".join(loop_parts)
    if approx_size_mb(out) > MAX_OUTPUT_GCODE_MB:
        raise GcodeSizeError(f"Output G-code exceeds {MAX_OUTPUT_GCODE_MB} MB limit (reduce loops/files)")
    return out

# ========== Runtime Estimation ==========
def parse_estimated_minutes(gcode_text):
    """Attempt to parse sliced time estimate (in minutes) from comments typical of Bambu / Cura style.
    Returns float minutes or None if not found.
    Searches for patterns like 'TIME:12345' (seconds) or ';TIME_ELAPSED:' and ';ESTIMATED_TIME:' etc.
    """
    # Common patterns
    patterns = [
        r";ESTIMATED_TIME:?\s*(\d+)",          # seconds
        r";TIME:(\d+)",                          # seconds
        r";PRINT_TIME:?\s*(\d+)",              # seconds
        r"; total estimated time \(s\): (\d+)", # seconds
        r"; layer_count: \d+.*?; total_time: (\d+)", # seconds maybe
    ]
    for pat in patterns:
        m = re.search(pat, gcode_text, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                seconds = int(m.group(1))
                if seconds > 0:
                    return seconds / 60.0
            except ValueError:
                continue
    # Try Bambu style JSON-ish comment lines like '; PRINT_ESTIMATE_TIME: 01:23:45'
    hm = re.search(r"PRINT_ESTIMATE_TIME:\s*(\d+):(\d+):(\d+)", gcode_text)
    if hm:
        h, m_, s_ = hm.groups()
        return (int(h) * 3600 + int(m_) * 60 + int(s_)) / 60.0
    return None

def estimate_combined_runtime_per_loop(file_infos, sweep_between_files, per_file_wait_min, sweep_pattern, sweep_interval_min):
    """Compute estimated minutes for one loop sequence (excluding between-loop wait)."""
    base = 0.0
    for info in file_infos:
        if info.get('minutes'):
            base += info['minutes']
    # Add waits between files
    if per_file_wait_min and len(file_infos) > 1:
        base += per_file_wait_min * (len(file_infos) - 1)
    # Approximate sweep time: rough guess from number of movement lines * small constant
    sweep_time_guess_min = max(0.1, sweep_pattern.count('\nG1') * 0.5 / 60.0)  # naive heuristic
    if sweep_between_files and len(file_infos) > 1:
        base += sweep_time_guess_min * (len(file_infos) - 1)
    return base, sweep_time_guess_min

# ========== Streamlit UI ==========
st.title("🖨️ Bambu Lab Print Looper")

uploaded_files = st.file_uploader(
    "📂 Upload one or more sliced .3mf files",
    type=["3mf"],
    accept_multiple_files=True,
    key="file_upload"
)

num_loops = st.number_input("🔁 Number of loop sequences", min_value=1, value=1, key="num_loops")
sweep_interval = st.number_input("⏱️ Minutes between loop sequences", min_value=0, value=60, key="sweep_interval")
disable_final_home = st.checkbox("🚫 Skip final homing (G28)", value=False, help="Leave unchecked unless you have a reason to avoid homing after final sweep.")

with st.expander("🧹 Sweep Pattern (optional override)"):
    custom_sweep = st.text_area(
        "Custom sweep G-code (leave blank to use default)",
        value="",
        placeholder="Paste or author a custom cleanup / purge / wipe pattern here..."
    )

sweep_between_files = False
per_file_wait = 0
order_input = None

if uploaded_files and len(uploaded_files) > 1:
    st.markdown("### 📑 Multi-file sequence settings")
    st.info("All uploaded files will be merged (in order) into one sequence, then that sequence loops.")
    st.caption("Enter order as comma-separated indices (e.g. 2,1,3). Leave blank for upload order.")
    order_input = st.text_input("Order of files (optional)")
    sweep_between_files = st.checkbox("Sweep between files inside a loop", value=True)
    per_file_wait = st.number_input("Minutes to wait between files (0 = none)", min_value=0, value=0)

# --- Integrate new limits + guarded logic in UI (wrap existing processing block) ---
# Find existing: if uploaded_files:
# Replace that entire try block with the version below

if uploaded_files:
    try:
        enforce_limits(num_loops, len(uploaded_files), custom_sweep)

        if len(uploaded_files) == 1:
            gtext, _gpath = extract_first_gcode_from_3mf(uploaded_files[0])
            single_minutes = parse_estimated_minutes(gtext)
            looped_gcode = create_looped_gcode(
                gtext,
                num_loops,
                sweep_interval,
                sweep_pattern_override=custom_sweep if custom_sweep.strip() else None,
                disable_final_home=disable_final_home
            )
            output_3mf = wrap_in_3mf(looped_gcode, uploaded_files[0])
            mode = "single"
            file_infos = [{"name": uploaded_files[0].name, "minutes": single_minutes}]
        else:
            ordered = uploaded_files
            if order_input:
                try:
                    idxs = [int(x.strip()) - 1 for x in order_input.split(",") if x.strip()]
                    if sorted(idxs) != list(range(len(uploaded_files))):
                        raise ValueError("Order must reference each file exactly once.")
                    ordered = [uploaded_files[i] for i in idxs]
                except Exception as oe:
                    st.error(f"Order parse error: {oe}")
                    st.stop()
            file_infos = []
            for f in ordered:
                try:
                    gtxt, _ = extract_first_gcode_from_3mf(f)
                    file_infos.append({"name": f.name, "minutes": parse_estimated_minutes(gtxt)})
                except Exception:
                    file_infos.append({"name": f.name, "minutes": None})
            looped_gcode = build_combined_looped_gcode(
                ordered,
                num_loops,
                sweep_interval,
                sweep_between_files=sweep_between_files,
                per_file_wait_min=per_file_wait,
                sweep_pattern_override=custom_sweep if custom_sweep.strip() else None,
                disable_final_home=disable_final_home
            )
            output_3mf = wrap_in_3mf(looped_gcode, ordered[0])
            mode = "multiple"

        size_mb = approx_size_mb(looped_gcode)
        if size_mb > MAX_OUTPUT_GCODE_MB * 0.9:
            st.warning(f"Large output ({size_mb:.1f} MB). Printer or slicer may refuse very large G-code.")

        st.success(f"✅ Created {'multi-file ' if mode=='multiple' else ''}looped 3MF with {num_loops} loop sequence(s). Size: {size_mb:.2f} MB")
        st.download_button(
            "⬇️ Download Looped 3MF",
            data=output_3mf,
            file_name=f"looped_{'combined_' if mode=='multiple' else ''}{uploaded_files[0].name}",
            mime="application/octet-stream"
        )

        with st.expander("ℹ️ Print Plan"):
            total_wait = (num_loops - 1) * sweep_interval
            st.write(f"Total inter-loop wait time: {total_wait} minutes")
            if mode == "multiple":
                st.write(f"Files per loop: {len(uploaded_files)}")
                st.write(f"Sweeps between files: {'Yes' if sweep_between_files else 'No'}")
                if per_file_wait:
                    st.write(f"Wait between files: {per_file_wait} min")
            st.write(f"Final homing: {'Disabled' if disable_final_home else 'Enabled'}")
            if custom_sweep.strip():
                st.write("Custom sweep pattern: Yes (override applied)")
            # Runtime estimates
            if any(fi.get('minutes') for fi in file_infos):
                sweep_pattern_used = custom_sweep if custom_sweep.strip() else get_sweep_pattern()
                per_loop_minutes, sweep_guess = estimate_combined_runtime_per_loop(
                    file_infos,
                    sweep_between_files if mode == 'multiple' else False,
                    per_file_wait if mode == 'multiple' else 0,
                    sweep_pattern_used,
                    sweep_interval
                )
                total_minutes = per_loop_minutes * num_loops + (num_loops - 1) * sweep_interval
                def fmt(m):
                    return f"{int(m//60)}h {(m%60):.0f}m" if m >= 60 else f"{m:.1f}m"
                st.markdown("**Estimated Runtime (very approximate)**")
                st.write("Per loop (print + in-loop waits/ sweeps):", fmt(per_loop_minutes))
                st.write("Between-loop waits:", fmt((num_loops -1)* sweep_interval))
                st.write("Total (all loops):", fmt(total_minutes))
                with st.expander("Per-file estimates"):
                    for fi in file_infos:
                        st.write(f"{fi['name']}: {fi['minutes']:.1f}m" if fi.get('minutes') else f"{fi['name']}: (unknown)")
                    st.caption(f"Sweep time guess per sweep: ~{sweep_guess:.2f}m (heuristic)")
        with st.expander("🔍 Preview (first 2000 chars)"):
            st.text_area("Preview", looped_gcode[:2000] + "\n... [truncated]", height=300)
    except (GcodeParseError, GcodeSizeError, ValueError) as ge:
        st.error(f"❌ {ge}")
    except Exception as e:
        st.exception(e)
