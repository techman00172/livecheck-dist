#!/bin/bash
# livecheck-assert.sh — run the ASSERT lines against the built chip (F5).
#
# Bound to F5 in Helix.  Touches the assert sentinel; the cmsis-svd LSP's
# sentinel poller sees it and runs the ( "check": ... ) assert lines against
# the freshly-built chip, publishing pass/fail in the editor gutter.
#
# Build first (F4 = reset + make upload) so every word exists, THEN press F5
# to verify the asserts.
touch /tmp/livecheck-assert-pending
