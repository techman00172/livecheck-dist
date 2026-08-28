#!/usr/bin/env python3
"""Upload Forth source to STM32 via the swdd daemon socket.

Works with any ST-Link (V2 or V3) — the daemon abstracts the debugger, so
there is nothing ST-Link specific here.

Usage: cat upload.fs | python3 swdd-upload.py
"""
import sys, socket, time

SOCK_PATH = "/tmp/swdd-forth.sock"
CMD_SOCK = "/tmp/swdd-cmd.sock"

# On a fast probe (ST-Link V3 at 24 MHz) the host can outrun a slow target's
# ring-buffer handshake while streaming code — long uploads corrupt
# ("compilettionarystart not found").  A slow F051 is the pacing item, not the
# host.  So: drop the SWD clock for the upload, restore it afterwards.
# Regmon register reads keep the fast clock.  (Terry's finding, 2026-08-20.)
UPLOAD_CLOCK_KHZ = 4800
FAST_CLOCK_KHZ = 24000

code = sys.stdin.read()
if not code.strip():
    print("Nothing to upload (stdin empty)")
    sys.exit(1)


def set_clock(khz):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(CMD_SOCK)
        s.sendall(("clock %d\n" % khz).encode())
        time.sleep(0.2)
        s.close()
    except OSError:
        pass  # daemon without clock support (older build) — ignore

set_clock(UPLOAD_CLOCK_KHZ)

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(10)
try:
    sock.connect(SOCK_PATH)
except (ConnectionRefusedError, FileNotFoundError):
    print("swdd daemon not running. Start with: sudo systemctl start swdd.service")
    sys.exit(1)

# Send the Forth source
sock.sendall(code.encode())
sock.sendall(b"\n")

# Wait for compilation to finish using a MARKER (Terry's speed fix 2026-08-25):
# the old loop waited for 5 quiet rounds (~10s of silence) which dominated the
# upload time.  Instead, send a unique marker comment AFTER the code; when its
# echo comes back the upload is genuinely done.  Measured: 10.7s -> 0.3s on a
# 115-line project (~35x faster).
import uuid
marker = "lc-done-%s" % uuid.uuid4().hex[:8]
sock.sendall(("( %s )\n" % marker).encode())
sock.settimeout(2)
out = b""
deadline = time.time() + 30.0   # overall cap so a wedged chip can't hang make forever
while marker.encode() not in out:
    if time.time() > deadline:
        break
    try:
        chunk = sock.recv(4096)
        if not chunk:
            break
        out += chunk
    except socket.timeout:
        # still compiling (or the echo was split); keep reading a little
        pass

if marker.encode() not in out:
    print("ERROR: chip did not confirm upload within 30s — the target is likely")
    print("wedged (stuck in a loop, or the ring buffer is jammed).  Reset it")
    print("(F4, or 'printf reset | socat - UNIX-CONNECT:/tmp/swdd-cmd.sock') and retry.")
    sys.exit(1)

sock.close()

set_clock(FAST_CLOCK_KHZ)

output = out.decode(errors="replace").strip()
if output:
    # Filter out the echo of what we sent
    lines = [l for l in output.split("\n") if l.strip() and l.strip() not in code.split("\n")]
    for l in lines:
        print(l)
print("Upload complete")
