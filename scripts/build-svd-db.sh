#!/bin/bash
# build-svd-db.sh — build a CMSIS-SVD relational database for ANY STM32 MCU.
#
# This is the mechanism that lets you use any STM32 chip, not just the ones
# whose databases ship in the release.  Give it the SVD file for your chip
# and it produces the -svd.db the language servers read:
#
#   ./scripts/build-svd-db.sh STM32G031     # uses STM32G031.svd, builds databases/STM32G031-svd.db
#
# Or from the demo dir (the make-driven way):
#
#   cd demo && MCU=STM32G031 make databases
#
# Change MCU in demo/Makefile, drop your <MCU>.svd beside it, run make, and
# LiveCheck knows your chip.  (xsltproc is required:  sudo pacman -S libxslt
#   /  sudo apt install libxslt1.1)
#
# Output: databases/<MCU>-svd.db  (the -svd suffix matches the release scheme)
set -e

MCU="${1:-STM32F051}"
SVD="${MCU}.svd"
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

GEMA="$PROJ/toolchain/gema"
PATTERNS="$PROJ/toolchain/patterns"
STYLES="$PROJ/toolchain/styles"
OUT_DB="$PROJ/databases/${MCU}-svd.db"

echo "=== Building SVD database for ${MCU} ==="

# Start from a clean file: db_rel.xsl uses CREATE TABLE IF NOT EXISTS, so
# building onto an existing DB would APPEND and duplicate every row.  Remove
# the old database first.
rm -f "$OUT_DB"

# Find the SVD file (beside the Makefile, in databases/, or in the project root).
SVD_PATH=""
for d in "$PROJ/demo" "$PROJ/databases" "$PROJ"; do
    if [ -f "$d/$SVD" ]; then SVD_PATH="$d/$SVD"; break; fi
done
[ -z "$SVD_PATH" ] && echo "Error: $SVD not found (try demo/, databases/, or the project root)" >&2 && exit 1
echo "SVD: $SVD_PATH"

# Step 1: Clean the SVD (transpose $ for 0x, Forth convention)
echo "  Cleaning..."
"$GEMA" -t -nobackup -line "$SVD_PATH" \
    -f "$PATTERNS/cleaned.pat" -out "$TMP/cleaned.svd"

# Step 2: Unfold derived registers
echo "  Unfolding..."
xsltproc -o "$TMP/unfolded.svd" "$STYLES/unfolded.xsl" "$TMP/cleaned.svd"

# Step 3: Compute absolute addresses from hex
echo "  Resolving addresses..."
xsltproc -o "$TMP/abs.svd" "$STYLES/process-hex2num.xsl" "$TMP/unfolded.svd"

# Step 4: Generate relational database
echo "  Building database..."
xsltproc -o "$TMP/db.sql" "$STYLES/db_rel.xsl" "$TMP/abs.svd"
sqlite3 "$OUT_DB" < "$TMP/db.sql" 2>/dev/null

echo "=== Done: databases/${MCU}-svd.db ==="
sqlite3 "$OUT_DB" \
    "SELECT '  ' || (SELECT COUNT(DISTINCT name) FROM peripheral) || ' peripherals, ' || (SELECT COUNT(*) FROM register) || ' registers, ' || (SELECT COUNT(*) FROM field) || ' bitfields'"
