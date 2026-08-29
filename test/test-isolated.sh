#!/usr/bin/env bash
# test-isolated.sh — run the LiveCheck manual install in total isolation and
# verify everything builds.  Runs INSIDE the podman container (built from
# test/Containerfile).  The repo checkout is available at /test-src
# (bind-mounted by the harness).
set -uo pipefail

REPO=/test-src
PASS=0
FAIL=0

ok()   { echo "  [ OK ]   $*"; PASS=$((PASS+1)); }
bad()  { echo "  [ FAIL ] $*"; FAIL=$((FAIL+1)); }

echo "=== LiveCheck isolated install test ==="
echo ""

# --- 0. Isolated? (nothing from Terry's box should be here) ---
echo "-- 0. Isolation check --"
if ls /home/tp 2>/dev/null; then
    bad "Terry's home dir is visible inside the container (not isolated!)"
else
    ok "No /home/tp — environment is isolated"
fi

# --- 1. Dependencies present ---
echo "-- 1. Dependencies --"
for dep in python3 hx xvfb-run; do
    if command -v "$dep" >/dev/null 2>&1; then
        ok "$dep"
    else
        bad "$dep missing"
    fi
done
if python3 -c "import tkinter" 2>/dev/null; then
    ok "python3 tkinter"
else
    bad "python3 tkinter missing"
fi

# --- 2. Distribution layout complete ---
echo "-- 2. Distribution contents --"
for f in README.md setup.sh \
         kernel/kernel-2.6.5-swd-bare.bin kernel/flash-kernel.sh \
         lsp/livecheck/site_paths.py \
         lsp/livecheck/mecrisp_lsp.py \
         lsp/livecheck/cmsis_svd_lsp.py \
         lsp/livecheck/forth_lint.py \
         lsp/livecheck/forth_livecheck.py \
         lsp/livecheck/project_summary.py \
         lsp/livecheck/mecrisp_mcp.py \
         lsp/livecheck/lsp_state.py \
         lsp/livecheck/livecheck_mcp.py \
         lsp/livecheck/mecrisp_stellaris.db \
         databases/ARM-Core.db databases/STM32F051-svd.db \
         databases/STM32F103-svd.db databases/STM32F407-svd.db \
         databases/STM32L0xx-svd.db databases/STM32G030-svd.db \
         databases/STM32F051-rm.db \
         toolchain/gema toolchain/swd2 toolchain/swdd \
         toolchain/patterns/bitfields.pat \
         toolchain/patterns/registers.pat \
         toolchain/patterns/constants.pat \
         toolchain/patterns/strip.pat \
         demo/demo.fs demo/Makefile \
         scripts/demo scripts/livecheck-reset.sh scripts/livecheck-assert.sh \
         scripts/summary-refresh.sh scripts/summary-tk.sh scripts/summary-tk.py; do
    if [ -f "$REPO/$f" ]; then
        ok "$f"
    else
        bad "$f missing"
    fi
done

# --- 3. site_paths resolves everything relocatably ---
echo "-- 3. site_paths resolution --"
if python3 -c "
import sys; sys.path.insert(0, '$REPO/lsp/livecheck')
import site_paths as sp
checks = [
    sp.toolchain('gema'),
    sp.pattern('bitfields.pat'),
    sp.database('STM32F051-svd.db'),
    sp.database('STM32F051-rm.db'),
    sp.script('summary-tk.sh'),
    sp.kernel('kernel-2.6.5-swd-bare.bin'),
    sp.lsp_db(),
]
assert all(c and __import__('os').path.isfile(c) for c in checks), checks
print('all resources resolve under the dist layout')
" 2>/tmp/site_paths.log; then
    ok "site_paths resolves under <dist>/"
else
    bad "site_paths failed: $(cat /tmp/site_paths.log | tail -2)"
fi

# --- 4. Python compiles (all LSP modules) ---
echo "-- 4. Python compile check --"
if ( cd "$REPO" && PYTHONPYCACHEPREFIX=/tmp/pyc python3 -m py_compile \
        lsp/livecheck/site_paths.py \
        lsp/livecheck/mecrisp_lsp.py \
        lsp/livecheck/cmsis_svd_lsp.py \
        lsp/livecheck/forth_lint.py \
        lsp/livecheck/forth_livecheck.py \
        lsp/livecheck/forth_single_step.py \
         lsp/livecheck/project_summary.py \
         lsp/livecheck/mecrisp_mcp.py \
         lsp/livecheck/lsp_state.py \
         lsp/livecheck/livecheck_mcp.py ); then
    ok "all LSP .py compile"
else
    bad "compile failed"
fi

# --- 4b. livecheck-mcp builds and registers its 6 tools ---
echo "-- 4b. livecheck-mcp server builds --"
# Needs the python 'mcp' package (installed in the container via pip; on
# Terry's box it's in the service venv).
if python3 -c "import mcp" >/dev/null 2>&1; then
    if ( cd "$REPO/lsp/livecheck" && python3 -c "
import livecheck_mcp, lsp_state
m = livecheck_mcp.build_mcp()
tools = sorted(t.name for t in m._tool_manager._tools.values())
need = ['active_documents','document_contents','document_diagnostics',
        'chip_state','project_summary','snapshot_age']
assert all(n in tools for n in need), (tools, need)
print('tools:', tools)
" ) >/tmp/mcp-build.log 2>&1; then
        ok "livecheck_mcp builds + registers all 6 tools"
    else
        bad "livecheck_mcp failed: $(tail -2 /tmp/mcp-build.log)"
    fi
else
    echo "  [ SKIP ] python 'mcp' package not in this interpreter"
fi

# --- 5. Databases are readable with content ---
echo "-- 5. Database contents --"
for db in ARM-Core STM32F051-svd STM32F103-svd STM32F407-svd STM32L0xx-svd STM32G030-svd; do
    n=$(sqlite3 "$REPO/databases/$db.db" "SELECT count(*) FROM peripheral;" 2>/dev/null)
    if [ -n "$n" ] && [ "$n" -gt 0 ]; then
        ok "$db.db: $n peripherals"
    else
        bad "$db.db unreadable/empty"
    fi
done

# --- 6. The dictionary DB has the FORTH + CUSTOM_FORTH tables ---
echo "-- 6. Mecrisp dictionary DB --"
n=$(sqlite3 "$REPO/lsp/livecheck/mecrisp_stellaris.db" "SELECT count(*) FROM FORTH;" 2>/dev/null)
if [ -n "$n" ] && [ "$n" -gt 100 ]; then
    ok "mecrisp_stellaris.db: $n words"
else
    bad "mecrisp_stellaris.db unreadable/too small (got '${n:-empty}')"
fi

# --- 7. The demo gema pipeline builds (resolves all CMSIS names) ---
echo "-- 7. Demo pipeline build --"
# The repo is mounted read-only, but the build writes outputs — copy the demo
# + toolchain to a writable dir first.
if ( mkdir -p /tmp/demowork \
     && cp -r "$REPO/demo" "$REPO/toolchain" "$REPO/scripts" /tmp/demowork/ \
     && cd /tmp/demowork/demo && make clean >/dev/null 2>&1 \
     && make check-ascii >/dev/null 2>&1 \
     && make upload.fs >/dev/null 2>&1 ); then
    if grep -qE "continue|GPIOB_MODER_MODER0" /tmp/demowork/demo/upload.fs 2>/dev/null; then
        ok "demo pipeline built and kept the intentionally-broken steps"
    else
        ok "demo pipeline built"
    fi
else
    bad "demo pipeline failed to build"
fi

# --- 7b. The SVD->database build mechanism works (make databases) ---
echo "-- 7b. SVD->database build (make databases) --"
# This is the 'use ANY STM32 chip' mechanism: give it an SVD, get a -svd.db.
# Requires xsltproc; the container may lack it, so build what we can.
if command -v xsltproc >/dev/null 2>&1; then
    if ( mkdir -p /tmp/demowork/databases \
         && cd /tmp/demowork/demo && MCU=STM32F103 make databases >/dev/null 2>&1 \
         && [ -f /tmp/demowork/databases/STM32F103-svd.db ] ); then
        n=$(sqlite3 /tmp/demowork/databases/STM32F103-svd.db \
            "SELECT count(*) FROM register;" 2>/dev/null)
        if [ "$n" = "722" ]; then
            ok "make databases built STM32F103-svd.db from its SVD ($n registers)"
        else
            bad "make databases built a DB but wrong size (got '$n', want 722)"
        fi
    else
        bad "make databases failed to build a database from the SVD"
    fi
else
    echo "  [ SKIP ] xsltproc not in the container — SVD build skipped"
fi

# --- 8. setup.sh runs (dependency check path) ---
echo "-- 8. setup.sh --"
if ( cd "$REPO" && bash setup.sh ) >/tmp/setup.log 2>&1; then
    ok "setup.sh completed"
else
    if grep -q "Missing required tools" /tmp/setup.log 2>/dev/null; then
        # st-flash / fossil aren't in the container — that's expected.
        ok "setup.sh ran the checks (missing probe/board tools — expected in container)"
    else
        bad "setup.sh failed early — log:"
        sed 's/^/       /' /tmp/setup.log | tail -10
    fi
fi

echo ""
echo "=== RESULT: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && echo "ALL TESTS PASSED" || echo "TESTS FAILED"
[ "$FAIL" -eq 0 ]
