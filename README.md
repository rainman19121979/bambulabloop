## Bambu Lab Print Looper

Generate a modified `.3mf` that re-runs one or more sliced prints in a controlled loop with optional sweeps, waits, and custom cleanup patterns. Useful for farm-style batch production without re-slicing or manually restarting jobs.

### Core Capabilities
* Single-file looping with configurable loop count & wait minutes between loops.
* Multi-file combine mode: merge several `.3mf` prints into a single composite sequence, then loop that composite set.
* Optional sweep (purge / wipe) pattern between: files, loops, final end.
* Custom sweep pattern override (author your own G-code motions/purges).
* Toggle to skip final homing (G28) if you want printer to remain where last sweep ends.
* Per-file runtime parsing (best-effort) and aggregated loop runtime estimates.
* Order control for multiple files (comma‑separated reordering in UI).

### Runtime Estimation
The app attempts to read estimated time comments (e.g. `;ESTIMATED_TIME:`, `;TIME:` or `PRINT_ESTIMATE_TIME:`) inside each embedded G-code. If found, it:
1. Sums file estimates.
2. Adds inter-file waits and approximate sweep time (heuristic based on G1 moves in sweep code).
3. Multiplies by loop count and adds between-loop waits.

Estimates are approximate; always consult your printer's live prediction.

### Usage
1. Slice models in Bambu Studio, export/save each `.3mf` (they must contain G-code — cloud-only jobs won't work).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch the app:
   ```bash
   streamlit run streamlit_app.py
   ```
4. Upload one or more `.3mf` files.
5. (Optional) Reorder multi-file sequence via indices (e.g. `2,1,3`).
6. Set loops, waits, sweeps, and custom pattern if desired.
7. Download the generated looped `.3mf` and print.

### Custom Sweep Pattern Tips
Provide raw G-code. Common inclusions:
```
M400           ; wait for moves to finish
G91 / G90      ; relative / absolute switches
G1 E-.. / E..  ; purge/retract
G4 S#          ; dwell seconds
```
Your pattern is injected verbatim; validate preview.

### Safety & Disclaimer
Batch / unattended printing increases risk. Always:
* Monitor first loop fully.
* Ensure nozzle/bed cooldown logic (if needed) is preserved.
* Validate that skipping homing will not cause collisions if enabled.

Use at your own risk. Review generated G-code before printing.

### Future Ideas
* Material/AMS slot change scripting per loop.
* Filament usage aggregation.
* More robust time extraction (parsing Bambu metadata XML if present).

PRs welcome!
