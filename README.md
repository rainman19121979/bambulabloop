# Bambu Lab Print Looper

Loop one or more sliced `.3mf` prints (Bambu Studio exports) into a single automated production job with optional waits, sweeps (cleanup moves), and runtime estimates.

## Key Features
- Single-file looping
- Multi-file combining (A → B → C …) then loop that set
- Custom file order (e.g. 3,1,2)
- Optional sweep between files and/or between loop sequences
- Optional wait (minutes) between files
- Configurable wait between loop sequences
- Custom sweep G-code override
- Optional skip of final homing (G28)
- Heuristic runtime estimation (per loop + total)
- Output packaged back into a valid `.3mf` (original assets preserved except G-code replaced)
- Safety limits on loops, file count, custom sweep size, and output size
- Preview of first 2000 chars of generated G-code

## How It Works
1. Upload one or more `.3mf` files (they must already contain sliced G-code).
2. App extracts the embedded `.gcode` (3MF is a ZIP container).
3. G-code is split into: header, print body (moves), footer.
4. For single file: print body is repeated N times with optional waits + sweeps.
5. For multiple files: each print body is concatenated (optional sweep/wait between) forming one base sequence; that sequence is looped.
6. Final sweep (and homing unless disabled) is appended.
7. New `.3mf` is built by copying original archive and swapping the G-code.
8. Download the new looped `.3mf` and send to printer.

## UI Options (Summary)
| Option | Purpose |
| ------ | ------- |
| Number of loop sequences | How many times to repeat (single or combined set) |
| Minutes between loop sequences | G4 dwell + sweep between each full loop |
| Order of files | Comma-separated 1-based indices |
| Sweep between files | Insert sweep pattern between combined files |
| Minutes to wait between files | Adds G4 dwell before next file in same loop |
| Custom sweep G-code | Override default cleanup moves everywhere |
| Skip final homing | Suppress last `G28` |
| Preview | First 2000 chars for safety review |

## Runtime Estimation
- Parses common slicer time comments (seconds → minutes).
- Unknown files show “(unknown)”.
- Sweep time guessed from count of movement lines in sweep pattern.
- Total time = (print + in-loop waits) * loops + between-loop waits.
- Estimates are approximate; verify on printer.

## Installation
```bash
git clone <repo-url>
cd bambulabloop
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Typical Scenarios
- Repeat one part 25 times overnight (set loops=25, interval=0).
- Produce a kit of 3 models repeatedly (upload 3 files, set loops>1).
- Insert cooling pause between different materials (per-file wait > 0).
- Use custom purge/wipe sequence (paste G-code in sweep override).
- Disable final homing for alignment-sensitive camera rig.

## Custom Sweep Notes
Provide only valid G-code fragment (no starting header). App appends it where needed. Size limit enforced (default 64 KB).

## Safety Limits (Defaults)
- Max loops: 500
- Max files: 30
- Max custom sweep: 64 KB
- Max output G-code: ~45 MB
Exceeding a limit raises a UI error.

## G-code Integrity
- Only first `.gcode` file inside each 3MF is used.
- If print body cannot be detected (markers missing), an error is shown with a diagnostic snippet.
- Extremely short bodies rejected.

## Troubleshooting
| Issue | Cause / Fix |
| ----- | ----------- |
| “No .gcode asset found” | Slice/export in Bambu Studio first |
| “Could not parse G-code structure” | Non-standard file; verify markers present |
| Output size limit error | Reduce loops or file count |
| Time estimate missing | Slicer did not embed recognizable time comment |
| Printer rejects job | G-code too large or unsupported commands in custom sweep |

## Good Practices
- Test with 1 loop before long runs.
- Avoid very large custom sweep blocks.
- Ensure purge / sweep motions stay within printable area.
- Monitor first repetition to confirm safe restart conditions (temp, bed adhesion).

## Future Ideas (Not Implemented)
- Filament usage aggregation
- Per-loop parameter drift (temp, speed)
- Preset sweep patterns
- Multi-G-code asset selection inside 3MF

## Disclaimer
Use at your own risk. Verify generated motions are safe for your printer setup.

## License
Add a license file if distributing.
