#!/bin/bash
# summary-refresh.sh — refresh the project summary from the LIVE chip (F5).
#
# Bound to F5 in Helix.  Touches the summary sentinel; the cmsis-svd LSP's
# sentinel poller sees it and re-reads the chip's CURRENT state (no make) —
# so after you build (F4) and run a word like `init`, F5 shows the true
# post-init registers instead of the build-time snapshot.
#
# F6 (livecheck-assert.sh) now runs the asserts.
touch /tmp/livecheck-summary-pending
