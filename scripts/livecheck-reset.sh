#!/bin/bash
# livecheck-reset.sh — F4: reset the board, then run make + LiveCheck.
#
# Bound to F4 in Helix (see ~/.config/helix/config.toml).  Two steps:
#   1. Sends 'reset' to the swdd cmd socket → ST-Link drives NRST (hardware
#      reset, CPU-independent — works even when Forth is locked up).
#   2. Touches the reset-pending sentinel.  The cmsis-svd LSP's sentinel
#      poller sees it and runs 'make upload' (the whole project, correct
#      order), then maps the compiler errors back to the source lines in the
#      editor gutter.  This is the SIMPLE MODE flow (Terry 2026-08-26):
#      F4 = reset + build, errors show in the editor, not just the terminal.
#
# No per-line-as-you-type checking — edit freely, F4 when you've reached a
# point, fix errors in the editor, F4 again.  F5 (livecheck-assert.sh) runs
# the ( "check": ... ) asserts against the freshly-built chip.

printf 'reset\n' | timeout 4 socat - UNIX-CONNECT:/tmp/swdd-cmd.sock
touch /tmp/livecheck-reset-pending
