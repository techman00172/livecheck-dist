#!/bin/bash
# summary-tk.sh — F6: open the F4 project summary.md in the Tkinter viewer.
#
# Single-instance: if the viewer is already open it reloads + raises itself
# instead of spawning a second window, so Terry can keep it parked beside the
# editor.  The open window ALSO auto-reloads whenever F4 regenerates summary.md
# (Terry 2026-08-27).
#
# Usage: summary-tk.sh [project-dir]
#   project-dir defaults to the current directory (Helix's :run-shell-command
#   runs in its working directory = the project dir).

HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${1:-.}"
FILE="$DIR/summary.md"
if [ ! -f "$FILE" ]; then
    echo "no summary.md in $DIR — press F4 (make upload) first to generate it"
    exit 1
fi
python3 "$HERE/summary-tk.py" "$FILE"
