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
         lsp/livecheck/mecrisp_stellaris.db \
         databases/ARM-Core.db databases/STM32F051.db \
         databases/STM32F103.db databases/STM32F407.db \
         databases/STM32L0xx.db databases/STM32G030.db \
         databases/database_rel.db \
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
    sp.database('STM32F051.db'),
    sp.database('database_rel.db'),
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
        lsp/livecheck/mecrisp_mcp.py ); then
    ok "all LSP .py compile"
else
    bad "compile failed"
fi

# --- 5. Databases are readable with content ---
echo "-- 5. Database contents --"
for db in ARM-Core STM32F051 STM32F103 STM32F407 STM32L0xx STM32G030; do
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
     && cp -r "$REPO/demo" "$REPO/toolchain" /tmp/demowork/ \
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
