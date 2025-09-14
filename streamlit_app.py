import streamlit as st
import zipfile
import io
import datetime

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

def create_looped_gcode(gcode_text, num_loops, sweep_interval_min):
    """Create G-code with loops and sweeps."""
    sweep_interval_sec = sweep_interval_min * 60

    # Define sweep pattern
    sweep = """
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

    # Extract G-code sections
    header, print_moves, footer = find_gcode_sections(gcode_text)
    
    # Build the looped G-code
    new_gcode = header
    
    for i in range(num_loops):
        new_gcode += f"\n; === LOOP {i+1} START ===\n"
        new_gcode += print_moves
        new_gcode += f"\n; === LOOP {i+1} END ===\n"
        
        # Add sweep and wait between loops except last
        if i < num_loops - 1:
            new_gcode += f"""
; --- WAITING AND SWEEPING ---
M400
G4 S{sweep_interval_sec} ; wait {sweep_interval_min} minutes
{sweep}
"""
    
    # Add final sweep and footer
    new_gcode += f"""
; --- FINAL SWEEP ---
{sweep}
G28 ; home all axes
"""
    new_gcode += footer
    
    return new_gcode

def wrap_in_3mf(gcode_text, input_3mf):
    """Create a new 3MF with looped G-code."""
    output = io.BytesIO()
    
    with zipfile.ZipFile(input_3mf, 'r') as src_zip:
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as dst_zip:
            # Copy all files from original 3MF except G-code
            for item in src_zip.filelist:
                if not item.filename.endswith('.gcode'):
                    dst_zip.writestr(item.filename, src_zip.read(item.filename))
            
            # Find original G-code path
            gcode_files = [f for f in src_zip.namelist() if f.endswith('.gcode')]
            if not gcode_files:
                raise ValueError("No G-code found in 3MF file")
            
            # Add new G-code using same path as original
            dst_zip.writestr(gcode_files[0], gcode_text)
    
    output.seek(0)
    return output

# ========== Streamlit UI ==========

# Remove the first UI section since we're using the updated version below

# Add new function to handle multiple files with loops
def build_combined_looped_gcode(three_mf_files, num_loops, sweep_interval_min):
    """Handle multiple 3MF files and create looped G-code with sweeps."""
    sweep_interval_sec = sweep_interval_min * 60
    sweep = get_sweep_pattern()

    # Get header from first file to preserve machine settings
    with zipfile.ZipFile(three_mf_files[0], "r") as zip_ref:
        gcode_files = [f for f in zip_ref.namelist() if f.endswith(".gcode")]
        if not gcode_files:
            raise ValueError(f"No G-code found inside first file. Please ensure it's sliced in Bambu Studio.")
        first_gcode = zip_ref.read(gcode_files[0]).decode("utf-8")
        header, _, _ = find_gcode_sections(first_gcode)

    # Combine all files into one sequence
    combined_base = header + "\n; === COMBINED FILES BASE SEQUENCE ===\n"
    
    for idx, uploaded_file in enumerate(three_mf_files):
        with zipfile.ZipFile(uploaded_file, "r") as zip_ref:
            gcode_files = [f for f in zip_ref.namelist() if f.endswith(".gcode")]
            if not gcode_files:
                raise ValueError(f"No G-code found inside {uploaded_file.name}. Slice it first in Bambu Studio.")
            gcode_text = zip_ref.read(gcode_files[0]).decode("utf-8")
            
            # Extract just the print moves
            _, print_moves, _ = find_gcode_sections(gcode_text)
            
            combined_base += f"\n; === FILE {idx+1}: {uploaded_file.name} START ===\n"
            combined_base += print_moves
            combined_base += f"\n; === FILE {idx+1}: {uploaded_file.name} END ===\n"
            
            # Add sweep between files except last
            if idx < len(three_mf_files) - 1:
                combined_base += f"\n; --- SWEEP BETWEEN FILES ---\n{sweep}\n"

    # Now create the final looped version
    final_gcode = "; === COMBINED AND LOOPED FARM MODE GCODE START ===\n"
    
    # Add the combined sequence multiple times based on num_loops
    for i in range(num_loops):
        final_gcode += f"\n; ====== LOOP {i+1} START ======\n"
        final_gcode += combined_base
        final_gcode += f"\n; ====== LOOP {i+1} END ======\n"
        
        # Add sweep between loops except last
        if i < num_loops - 1:
            final_gcode += f"""
; --- SWEEP BETWEEN LOOPS ---
M400
G4 S{sweep_interval_sec} ; wait {sweep_interval_min} minutes
{sweep}
"""

    # Final sweep + homing
    final_gcode += f"""
; --- FINAL SWEEP ---
M400
{sweep}
G28 ; home all axes
; === COMBINED AND LOOPED FARM MODE GCODE END ===
"""
    return final_gcode

# Update the Streamlit UI section
st.title("🖨️ Bambu Lab Print Looper")

uploaded_files = st.file_uploader(
    "📂 Upload one or more sliced .3mf files", 
    type=["3mf"], 
    accept_multiple_files=True,
    key="file_upload"
)

num_loops = st.number_input("🔁 Number of loops", min_value=1, value=1, key="num_loops")
sweep_interval = st.number_input("⏱️ Minutes between loops", min_value=1, value=60, key="sweep_interval")

if uploaded_files:
    try:
        if len(uploaded_files) == 1:
            # Single file mode - read and create looped version
            with zipfile.ZipFile(uploaded_files[0], "r") as zip_ref:
                gcode_files = [f for f in zip_ref.namelist() if f.endswith('.gcode')]
                if not gcode_files:
                    st.error("No G-code found. Please slice the model in Bambu Studio first.")
                    st.stop()
                
                original_gcode = zip_ref.read(gcode_files[0]).decode('utf-8')
                looped_gcode = create_looped_gcode(original_gcode, num_loops, sweep_interval)
                output_3mf = wrap_in_3mf(looped_gcode, uploaded_files[0])
                mode = "single"
        else:
            # Multiple files mode - combine and create looped version
            looped_gcode = build_combined_looped_gcode(uploaded_files, num_loops, sweep_interval)
            output_3mf = wrap_in_3mf(looped_gcode, uploaded_files[0])  # Use first file as template
            mode = "multiple"
            
        st.success(f"✅ Created {'combined ' if mode == 'multiple' else ''}farm mode 3MF with {num_loops} loops!")
        
        # Add download button
        st.download_button(
            "⬇️ Download Looped 3MF",
            data=output_3mf,
            file_name=f"looped_{'combined_' if mode == 'multiple' else ''}{uploaded_files[0].name}",
            mime="application/octet-stream"
        )
        
        # Add information
        with st.expander("ℹ️ Print Information"):
            total_time = sweep_interval * (num_loops - 1)
            hours = total_time // 60
            minutes = total_time % 60
            
            if mode == "multiple":
                st.info(f"""
                Print Schedule:
                - Number of files: {len(uploaded_files)}
                - Number of loop sequences: {num_loops}
                - Time between loop sequences: {sweep_interval} minutes
                - Total time between first and last sequence: {hours}h {minutes}m
                
                What happens:
                1. Prints all files in sequence
                2. Does auto-sweep between files
                3. Waits {sweep_interval} minutes after sequence
                4. Repeats sequence {num_loops} times
                5. Does final sweep and homes
                """)
            else:
                st.info(f"""
                Print Schedule:
                - Number of prints: {num_loops}
                - Time between prints: {sweep_interval} minutes
                - Total time between first and last print: {hours}h {minutes}m
                
                What happens:
                1. Print completes
                2. Waits {sweep_interval} minutes
                3. Does auto-sweep of the bed
                4. Starts next print
                5. Repeats until all {num_loops} prints are done
                """)
        
        with st.expander("🔍 Preview G-code"):
            st.text_area(
                "Preview", 
                looped_gcode[:2000] + "\n... [truncated]", 
                height=300
            )
    except Exception as e:
        st.error(f"⚠️ Error: {str(e)}")
