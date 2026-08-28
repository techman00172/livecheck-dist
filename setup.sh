#!/usr/bin/env bash
# setup.sh — MANUAL install of LiveCheck (F051 debug kernel + live-silicon
# checking in Helix).  No AI required — this is the human-readable install.
#
# What it does:
#   1. checks the tools you need (python3, tkinter, helix, stlink, fossil)
#   2. checks/installs the python deps for the two language servers
#   3. links the F4/F5/F6 helper scripts + swdd into ~/.local/bin
#   4. appends the Helix language config that binds the LSPs
#   5. prints the flash-the-kernel + try-the-demo steps
#
# Usage:  ./setup.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
HELIX_CONFIG="${HOME}/.config/helix"
PY_DEP_DIR="$HERE/lsp/livecheck"

echo "==> LiveCheck installer (manual — no AI needed)"
echo ""

need() {  # need <tool> <why>
    if command -v "$1" >/dev/null 2>&1; then
        echo "  [   OK    ] $1 — $2"
    else
        echo "  [ MISSING ] $1 — $2"
        return 1
    fi
}

FAIL=0

# --- core tools ---
need python3 "the language servers run on it"        || FAIL=1
need hx "the editor LiveCheck hooks into"            || FAIL=1
need st-flash "to flash the F051 debug kernel"        || FAIL=1
need fossil "to open this project's repository"       || FAIL=1

# --- python tkinter ---
if python3 -c "import tkinter" 2>/dev/null; then
    echo "  [   OK    ] python3 tkinter"
else
    echo "  [ MISSING ] tkinter for python3."
    echo "             Arch:   sudo pacman -S tk"
    echo "             Debian: sudo apt install python3-tk"
    FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then
    echo ""
    echo "==> Missing required tools above.  Install them and re-run."
    exit 1
fi

# --- python deps for the LSPs (pygls + lsprotocol) ---
echo "-- python dependencies --"
if pip install --user -r "$PY_DEP_DIR/requirements.txt" 2>/dev/null; then
    echo "  [   OK    ] pygls + lsprotocol installed"
else
    echo "  [  INFO   ] pip install failed (may need a venv) — the LSPs need"
    echo "              pygls>=0.6.0 and lsprotocol>=1.4.0 to run."
fi

# --- link helper scripts + swdd into ~/.local/bin ---
echo "-- helper scripts --"
mkdir -p "$BIN_DIR"
for name in livecheck-reset.sh livecheck-assert.sh summary-refresh.sh \
            summary-tk.py summary-tk.sh swdd; do
    src="$HERE/scripts/$name"
    [ "$name" = "swdd" ] && src="$HERE/toolchain/swdd"
    if [ ! -f "$src" ]; then
        echo "  [ WARNING ] $name not found in the repo — skipping"
        continue
    fi
    dst="$BIN_DIR/$name"
    if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
        echo "  [   OK    ] $name — already linked"
    elif [ -e "$dst" ]; then
        echo "  [ WARNING ] $dst exists — not overwriting"
    else
        ln -s "$src" "$dst"
        echo "  [   LINK  ] $dst -> $src"
    fi
done

# --- Helix language config ---
echo "-- Helix language config --"
mkdir -p "$HELIX_CONFIG"
LCONF="$HELIX_CONFIG/languages.toml"
LSP_DIR="$HERE/lsp/livecheck"
if grep -q "mecrisp_lsp" "$LCONF" 2>/dev/null; then
    echo "  [   OK    ] LiveCheck LSPs already configured in $LCONF"
else
    cat >> "$LCONF" <<EOF

# --- LiveCheck (appended by setup.sh) ---
[[language]]
name = "forth"
scope = "source.forth"
injection-regex = "forth"
file-types = ["fs"]
comment-token = "\\"
indent = { tab-width = 4, unit = "\t" }
language-servers = ["mecrisp_lsp", "cmsis_svd_lsp"]

[language-server.mecrisp_lsp]
command = "python3"
args = ["$LSP_DIR/mecrisp_lsp.py"]

[language-server.cmsis_svd_lsp]
command = "python3"
args = ["$LSP_DIR/cmsis_svd_lsp.py"]
EOF
    echo "  [  ADDED  ] LiveCheck LSPs appended to $LCONF"
    echo "             (restart Helix for it to take effect)"
fi

echo ""
echo "==> Done.  Two more manual steps:"
echo ""
echo "  1. Flash the F051 debug kernel (one time):"
echo "       cd $HERE/kernel"
echo "       ./flash-kernel.sh"
echo "     (needs an ST-Link probe wired to the board's SWDIO/SWCLK)"
echo ""
echo "  2. Try the demo:"
echo "       $HERE/scripts/demo /tmp/livecheck-work"
echo "       cd /tmp/livecheck-work/src"
echo "       hx demo.fs"
echo "     Then press F4 in Helix: reset + build + upload.  Blue check mark"
echo "     = the chip accepted the line; orange = hover to see why."
echo ""
echo "  F4 = reset + make upload    F5 = refresh live summary"
echo "  F6 = run the asserts"
