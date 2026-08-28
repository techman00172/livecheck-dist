#!/usr/bin/env python3
"""forth_single_step.py — run one line of Forth on the bench and check the result.

The "Forth single-stepper": as a technician types each line of Forth in the
editor, this module can run that ONE line on the real chip (via the swdd
Forth socket) and read back the registers the line touched (via the swdd
command socket) — reporting success/failure.  The Forth equivalent of
single-stepping assembly/C, but at the code-building stage.

Editor-agnostic: the LSP orchestrates it.  Any editor (Helix, nvim, ...) that
speaks LSP triggers it; this module does the bench work.

Socket protocol:
  /tmp/swdd-forth.sock  — the Mecrisp Forth console (send line, get "ok.")
  /tmp/swdd-cmd.sock    — swdd command socket ("mem <hexaddr> <nbytes>")
"""
import re
import socket
import time

FORTH_SOCK = "/tmp/swdd-forth.sock"
CMD_SOCK = "/tmp/swdd-cmd.sock"

# Danger words that must NOT be auto-run: they erase flash / wipe the
# dictionary mid-session.
DANGER_WORDS = ["eraseflash", "eraseflashfrom", "flashpageerase"]


# ---------------------------------------------------------------------------
# Forth socket: send a line, get the reply
# ---------------------------------------------------------------------------
def run_line(line, timeout=4.0, settle=0.6):
    """Send one line of Forth to the bench.  Returns the raw reply."""
    if not line or not line.strip():
        return ""
    # strip a trailing comment (the LSP already filters comments; belt+braces)
    line = line.split("\\")[0].strip()
    if not line:
        return ""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(FORTH_SOCK)
    except OSError as e:
        return f"ERROR: cannot connect to Forth socket ({e})"
    time.sleep(settle)
    s.sendall((line + "\n").encode())
    time.sleep(settle)
    data = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(chunk) < 4096:
                break
    except socket.timeout:
        pass
    s.close()
    return data.decode(errors="replace").strip()


def line_succeeded(reply):
    """Did the line run OK?  Mecrisp replies 'ok.' on success; an error
    names the problem (e.g. 'not found.', 'Stack underflow', '?') and ends
    without 'ok.'."""
    if not reply:
        return False
    return "ok." in reply and "not found" not in reply


# ---------------------------------------------------------------------------
# Register detection + readback
# ---------------------------------------------------------------------------
# F0 register base addresses (from the SVD).  The LSP's SVD DB knows these;
# this minimal table covers the common ones for the prototype.
REG_ADDRS = {
    "RCC_CR": 0x40021000,
    "RCC_CFGR": 0x40021004,
    "RCC_CIR": 0x40021008,
    "RCC_AHBRSTR": 0x4002100C,
    "RCC_APB2RSTR": 0x40021010,
    "RCC_APB1RSTR": 0x40021014,
    "RCC_AHBENR": 0x40021014,
    "GPIOA_MODER": 0x48000000,
    "GPIOB_MODER": 0x48000400,
    "GPIOC_MODER": 0x48000800,
    "GPIOA_ODR": 0x48000014,
    "GPIOB_ODR": 0x48000414,
    "GPIOC_ODR": 0x48000814,
}


def touched_registers(line):
    """Find the registers a line mentions (RCC_CFGR, GPIOB_ODR, ...).
    Handles 'RCC_CFGR', 'RCC_CFGR_PLLMUL' (underscore), and the gema dash
    form 'GPIOB-ODR-bit0' (normalised to underscores first)."""
    norm = re.sub(r"-", "_", line)
    found = []
    for reg in REG_ADDRS:
        if re.search(r"\b" + re.escape(reg) + r"(?:_[A-Za-z0-9]+)*\b", norm):
            found.append(reg)
    return found


def read_register(reg, timeout=4.0):
    """Read a register's live value via the swdd command socket."""
    addr = REG_ADDRS.get(reg.upper())
    if addr is None:
        return None
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(CMD_SOCK)
    except OSError:
        return None
    s.sendall(("mem %x 4\n" % addr).encode())
    data = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if data.rstrip().endswith(b"."):
                break
    except socket.timeout:
        pass
    s.close()
    m = re.search(rb":\s*([0-9a-fA-F]{2}) ([0-9a-fA-F]{2}) ([0-9a-fA-F]{2}) ([0-9a-fA-F]{2})", data)
    if not m:
        return None
    b = [int(m.group(i), 16) for i in range(1, 5)]
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)


# ---------------------------------------------------------------------------
# The main entry point — what the LSP calls
# ---------------------------------------------------------------------------
def single_step(line, check_registers=True):
    """Run one line on the bench; return a structured result."""
    if not line or not line.strip():
        return {"ok": False, "reply": "", "error": "empty line"}
    # danger-word guard
    for w in DANGER_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", line):
            return {"ok": False, "reply": line, "error": "DANGER: %s refused (would erase flash)" % w}

    reply = run_line(line)
    ok = line_succeeded(reply)
    regs = {}
    if check_registers and ok:
        for reg in touched_registers(line):
            regs[reg] = read_register(reg)

    return {
        "ok": ok,
        "reply": reply,
        "registers": regs,
        "error": "" if ok else (reply or "no reply from bench"),
    }


def main():
    """CLI: ./forth_single_step.py 'line of forth'"""
    import json
    import sys
    line = " ".join(sys.argv[1:]).strip()
    if not line:
        print("usage: forth_single_step.py '<forth line>'")
        return 1
    result = single_step(line)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
