#!/usr/bin/env python3
"""forth_livecheck.py — LiveCheck: live per-line Forth compilation via the LSP.

The LSP's LiveCheck feature: as a technician types Forth in Helix, each
COMPLETED line is sent to the live bench's compiler over SWD, and the ok/error
is published back as a diagnostic in the editor gutter.  This module does the
bench work; the LSP (cmsis-svd-lsp) orchestrates it.

TERRY'S INVARIANT (2026-08-24): if every previous line compiled 'ok.', then by
construction every word the current line depends on already exists on the
board — dependencies are satisfied automatically, no separate dependency scan
needed.  So LiveCheck only needs to verify the current line's ok/fail, and the
accumulated 'ok.' history IS the dependency check.

SAFETY:
  - DANGER_WORDS (from forth_single_step) refuse flash-erase words.
  - DENY_WORDS (mirror of the forth-gateway deny-list) refuse
    compiletoflash/compiletoram/cornerstone — agents (and the LSP) must not
    change what is in flash.
  - LOCK-DETECT: if a line gets NO reply at all (the bench has locked up in an
    infinite loop — a Forth 'reset' word can't help because the CPU is not
    executing), send a HARDWARE reset through SWD (NRST on the ST-Link V3,
    via swdd's 'reset' command — the same path the forth-gateway forth_reset
    tool uses).  The ST-Link drives NRST at the pin level, bypassing the CPU.
"""
import os
import re
import socket
import sqlite3
import subprocess
import threading
import time
import uuid

from forth_single_step import run_line, line_succeeded

FORTH_SOCK = "/tmp/swdd-forth.sock"
CMD_SOCK = "/tmp/swdd-cmd.sock"

# Serialise ALL Forth-socket traffic (Terry 2026-08-26).  make upload (the F4
# path) and the per-line _fast_run both stream over /tmp/swdd-forth.sock.  If
# they run concurrently (the sentinel poller thread firing livecheck_run while
# the main thread handles a didChange scan), their byte streams interleave —
# the terminal showed 'lmt01.on not found' because the assert line landed
# mid-upload before the word was defined.  Every socket transaction takes this
# lock, so the upload and the per-line sends are strictly sequential.
_FORTH_LOCK = threading.RLock()

# ANSI escape sequence (colour codes Mecrisp sends, e.g. '\x1b[36m').  Stripped
# from replies before they are shown in the editor gutter — raw codes clutter
# the display (Terry #251/#252, 2026-08-25).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text):
    """Remove ANSI colour codes from a string."""
    if not text:
        return text
    return _ANSI_RE.sub("", text)

# LiveCheck's own fast bench send.  forth_single_step.run_line() sleeps 0.6s
# BEFORE and AFTER each line (1.2s/line) — fine for one manual single-step, but
# a 40-line LiveCheck scan would take ~48s and BLOCK the LSP's completions
# meanwhile.  The chip replies in milliseconds, so LiveCheck uses a marker-
# based send (the same pattern the forth-gateway proved): insert a unique
# 'gw:xxxx' comment, send the line, then read until the reply arrives.
MARKER_PREFIX = "gw:"
_FAST_SETTLE = 0.05   # the chip echoes + replies in ms; 50ms is generous

# Mecrisp error messages -> plain-English meaning + fix.  Used to explain a
# failed line in the editor gutter.  (Full reference on the wiki 'forth-errors'.)
FORTH_ERRORS = {
    "jump too far": ("Dreaded conditional-jump range limitation. "
                     "Split into smaller words, or make a new word for the "
                     "offending code."),
    "cannot write into core": ("Flash write refused — wrong address/data, or "
                               "flash protected."),
    "create needs name": ("'create' needs a name — often a lone ';' in the "
                          "wrong place."),
    "flash full": ("The chip's flash memory is full.  Erase/reclaim flash, or "
                   "develop in RAM."),
    "is compile only": ("Cannot be used interactively — must be inside a "
                        "definition."),
    "not enough ram": ("Not enough RAM to complete the word.  Small chip; "
                       "big definition."),
    "not found": ("Name (word/constant/variable) not found — usually a source "
                  "typo, or the word isn't loaded yet."),
    "ram full": ("The chip's RAM is full.  Must reset, or move to flash."),
    "redefine": ("Defined more than once.  Expected on re-upload of the same "
                 "source."),
    "stack underflow": ("The data stack was empty — a word consumed more than "
                        "it was given."),
    "stack not balanced": ("Return stack unbalanced — use of >R and R> was "
                           "not equal."),
    "stack overflow": ("Data stack full (default 64 elements)."),
    "structures don't match": ("Control structure incomplete — e.g. a missing "
                               "'then' from an 'if ... then'."),
    "unhandled interrupt": ("An interrupt fired with no handler."),
    "variables collide with dictionary": ("A variable's address collides with "
                                          "the dictionary area."),
    "wrong address or data for writing flash": ("Flash write with bad address "
                                                "or data."),
}


def explain_error(reply):
    """Look up a Mecrisp error reply and return its plain-English meaning.
    Returns '' if no known error matches (the raw reply stands alone)."""
    low = (reply or "").lower()
    for msg, meaning in FORTH_ERRORS.items():
        if msg in low:
            return meaning
    return ""


def _fast_run(line):
    """Send ONE line to the bench FAST (marker-based).  Returns the reply."""
    with _FORTH_LOCK:
        return _fast_run_locked(line)


def _fast_run_locked(line):
    """The actual send/read, run while holding the Forth socket lock."""
    marker = MARKER_PREFIX + uuid.uuid4().hex[:8]
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # Short timeout: the chip replies in ms, and a 2s block here would hold a
    # thread-pool worker hostage on shutdown (Helix: "Timed out waiting for
    # language servers").  0.5s is generous for a real reply and bounded for a
    # stuck line.
    s.settimeout(0.5)
    try:
        s.connect(FORTH_SOCK)
        s.sendall(("( %s )\n" % marker).encode())
        s.sendall((line + "\n").encode())
        time.sleep(_FAST_SETTLE)
        data = b""
        # Read until our LINE has been echoed back by Mecrisp (the marker's own
        # 'ok.' appears first, so 'ok.' alone is NOT enough — wait for the line
        # text to come back).  The trailing 'ok.'/'not found' usually arrives in
        # the SAME read as the echo, so once the line is seen we do a SHORT
        # non-blocking drain (2ms) instead of a blocking poll — a full blocking
        # recv here would wait ~150ms/line (the tail-wait bottleneck that made
        # LiveCheck rechecks take 15s for 61 lines).
        need = line.strip().encode()
        while True:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
            if need and need in data:
                # line echoed — do a brief non-blocking drain for the trailing
                # result marker (swdd keeps the socket open; a short settimeout
                # drains whatever's already buffered without blocking long).
                s.setblocking(False)
                try:
                    tail = s.recv(4096)
                    if tail:
                        data += tail
                except (BlockingIOError, OSError):
                    pass
                finally:
                    s.setblocking(True)
                break
        return data.decode(errors="replace").strip()
    except OSError as e:
        return "ERROR: cannot connect to Forth socket (%s)" % e
    finally:
        try:
            s.close()
        except OSError:
            pass

# The Mecrisp boot banner appears in the live reply stream when the board
# resets (by Ctrl-C, a crash, cornerstone, a power blip).  Its presence in a
# reply is the ground-truth "RAM dictionary was wiped" signal — LiveCheck
# must invalidate its accumulated green history when it sees it, because the
# editor's "every previous line compiled ok." is only true while the board's
# RAM state is unchanged.  (Terry develops in RAM: a reset erases all words.)
BANNER_MARKER = "Mecrisp-Stellaris"

# Flash-erase / dictionary-wipe words (from forth_single_step's DANGER_WORDS)
DANGER_WORDS = ["eraseflash", "eraseflashfrom", "flashpageerase"]
# Flash-target / persistence words (mirror of the forth-gateway deny-list)
DENY_WORDS = ["compiletoflash", "compiletoram", "cornerstone", "flashforget"]

# How long to wait for a reply before declaring the bench locked.
LOCK_TIMEOUT = 2.0

# Per-URI live state: whether the board's RAM dictionary still matches the
# editor's accumulated green history.  Set False when the banner appears (a
# reset wiped RAM); the LSP then re-runs `make upload` and re-checks from the
# top of the file.  Keyed by text-document URI because several files may be
# open at once.
_history_valid = {}
# GLOBAL reset flag: after a hardware reset, EVERY file's history is invalid,
# including files never checked before (which have no per-URI entry and would
# otherwise default to valid).  mark_history_valid(uri) clears it for that URI.
_reset_pending_global = False


def history_valid(uri):
    """Is the editor's accumulated history still valid for this file?
    False if a global reset happened (covers unrecorded files too)."""
    if _reset_pending_global:
        return False
    return _history_valid.get(uri, True)


def invalidate_history(uri):
    """A reset wiped the board's RAM dictionary — mark the editor's history
    invalid so LiveCheck re-uploads and re-checks from the top."""
    _history_valid[uri] = False


def invalidate_all():
    """A hardware reset wipes the WHOLE chip's RAM dictionary.  Sets the GLOBAL
    flag so any file checked next is treated as invalid (it must recover /
    re-upload before its markers are trusted).  Deliberately does NOT flip
    every per-URI entry: dependency files stay 'valid' — they are unchanged,
    and the FIRST file to recover runs 'make upload', which re-populates the
    whole chip (including those dependencies).  Invalidating them would only
    cause redundant re-uploads.  Other files are handled when THEY are
    checked (Terry 2026-08-25)."""
    global _reset_pending_global
    _reset_pending_global = True


def mark_history_valid(uri):
    """After a successful re-upload + re-check, the history is valid again."""
    global _reset_pending_global
    _reset_pending_global = False
    _history_valid[uri] = True


def mark_all_history_valid():
    """After ONE successful 'make upload', the WHOLE chip is re-populated —
    every file's history is valid again (the upload defines all words,
    dependencies included).  Clearing only ONE uri (mark_history_valid) let
    other open files re-trigger recover() -> another make upload -> the
    Redefine storm after F4 (Terry 2026-08-26).  A single upload must mark
    everything valid."""
    global _reset_pending_global
    _reset_pending_global = False
    for k in _history_valid:
        _history_valid[k] = True


# RESET-PENDING SENTINEL: the shell reset path (F4 -> livecheck-reset.sh) runs
# outside the LSP process and cannot call invalidate_all() directly.  It touches
# this file after resetting; the LSP checks it on the next scan and invalidates
# all open files.  The LSP 'livecheck.reset' command calls invalidate_all()
# directly (no sentinel needed).
_RESET_SENTINEL = "/tmp/livecheck-reset-pending"
_ASSERT_SENTINEL = "/tmp/livecheck-assert-pending"
_SUMMARY_SENTINEL = "/tmp/livecheck-summary-pending"


def touch_summary_sentinel():
    """Mark that the user pressed F5 (refresh the summary from the live chip).
    Called by the shell summary script (summary-refresh.sh), outside the LSP."""
    try:
        with open(_SUMMARY_SENTINEL, "w") as f:
            f.write("summary\n")
    except OSError:
        pass


def consume_summary_sentinel():
    """If a summary refresh is requested, remove the sentinel and return True."""
    if os.path.isfile(_SUMMARY_SENTINEL):
        try:
            os.remove(_SUMMARY_SENTINEL)
        except OSError:
            pass
        return True
    return False


def touch_reset_sentinel():
    """Mark that a reset happened (called by the shell reset script)."""
    try:
        with open(_RESET_SENTINEL, "w") as f:
            f.write("reset\n")
    except OSError:
        pass


def touch_assert_sentinel():
    """Mark that the user pressed F5 (run the asserts).  Called by the shell
    assert script (livecheck-assert.sh), outside the LSP process."""
    try:
        with open(_ASSERT_SENTINEL, "w") as f:
            f.write("assert\n")
    except OSError:
        pass


def consume_assert_sentinel():
    """If the user pressed F5 (run asserts), return True and clear the
    sentinel so it only fires once."""
    if os.path.isfile(_ASSERT_SENTINEL):
        try:
            os.remove(_ASSERT_SENTINEL)
        except OSError:
            pass
        return True
    return False


def reset_pending():
    """True if a reset happened since the last make (sentinel present).  Does
    NOT remove the sentinel — only consume_reset_sentinel() consumes it, so the
    F4 poller still fires make after this check (Terry 2026-08-27: the old
    non-destructive split meant _publish_with_livecheck ate the sentinel first
    and F4's make never ran, so summary.fs was never regenerated)."""
    return os.path.isfile(_RESET_SENTINEL)


def consume_reset_sentinel():
    """If a reset happened since the last scan, invalidate all history and
    return True.  Removes the sentinel so it only fires once."""
    if os.path.isfile(_RESET_SENTINEL):
        try:
            os.remove(_RESET_SENTINEL)
        except OSError:
            pass
        invalidate_all()
        return True
    return False


def banner_in_reply(reply):
    """Does the reply contain the Mecrisp boot banner?  True = the board just
    reset, so the RAM dictionary was wiped."""
    return bool(reply) and BANNER_MARKER in reply


def _denied(line):
    """Return the first denied word in the line, else None."""
    for w in DANGER_WORDS + DENY_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", line):
            return w
    return None


def is_code_line(line):
    """Is this a line worth sending to the bench?  Skips blanks, comments
    ('\\' to EOL, '(' ... ')' inline), and pure stack-effect comments."""
    s = line.strip()
    if not s:
        return False
    if s.startswith("\\"):
        return False
    # a line that is ONLY a parenthesised comment / stack effect
    if re.fullmatch(r"\([^)]*\)", s):
        return False
    return True


# CMSIS-SVD register-name pattern: PERIPH_REG, PERIPH_REG_FIELD, or
# PERIPH_REG_FIELD_BIT (e.g. RCC_AHBENR_IOPAEN, GPIOA_MODER_MODER9,
# GPIOC_OTYPER_OT5).  The SAME pattern the cmsis-svd-lsp uses to find and
# validate register names against the SVD database.
_SVD_NAME_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,6}(?:_[A-Z0-9]{1,}){1,3}\b")


def contains_svd_name(line):
    """Does the line contain a CMSIS-SVD register name?

    SVD names (RCC_AHBENR_IOPAEN, GPIOA_MODER_MODER9, ...) are NOT Forth
    words — they are rewritten to raw addresses by the gema pipeline at
    UPLOAD time.  The chip never sees them.  LiveCheck therefore RESOLVES them
    through gema and sends the RESOLVED line to the chip (see
    resolve_svd_line) — so the chip checks the real instruction, and 'if it
    passes here, upload will pass'.
    """
    return bool(_SVD_NAME_RE.search(line))


# The 4-stage gema pipeline (same as the Makefile 'upload' target): the SVD
# names in the source are rewritten to absolute addresses + bit offsets.  A
# single line is run through the SAME pipeline so the chip sees exactly what
# 'make upload' would send.
import site_paths
_GEMA = site_paths.toolchain("gema")
_PATTERNS = [
    site_paths.pattern("bitfields.pat"),
    site_paths.pattern("registers.pat"),
    site_paths.pattern("constants.pat"),
    site_paths.pattern("strip.pat"),
]


def resolve_svd_line(line):
    """Run ONE line through the 4-stage gema pipeline; return the resolved
    Forth (addresses instead of SVD names), or None if resolution failed."""
    if not contains_svd_name(line):
        return line
    import tempfile
    try:
        inp = tempfile.NamedTemporaryFile("w", suffix=".fs", delete=False)
        inp.write(line + "\n")
        inp.close()
        out = line
        for pat in _PATTERNS:
            tmp = tempfile.NamedTemporaryFile("w", suffix=".fs", delete=False)
            tmp.close()
            r = subprocess.run(
                [_GEMA, "-t", "-nobackup", "-line", inp.name,
                 "-f", pat, "-out", tmp.name],
                capture_output=True, text=True, timeout=30)
            inp.close()
            import os as _os
            try:
                _os.unlink(inp.name)
            except OSError:
                pass
            if r.returncode != 0:
                try:
                    _os.unlink(tmp.name)
                except OSError:
                    pass
                return None
            out = open(tmp.name).read().strip()
            inp = tmp
        try:
            _os.unlink(inp.name)
        except OSError:
            pass
        return out or None
    except Exception:
        return None


def hw_reset():
    """Hardware reset via SWD NRST (ST-Link drives the reset pin, bypassing
    the CPU — works even when the board is locked in a loop).  Returns a
    short status string."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3.0)
    try:
        s.connect(CMD_SOCK)
        s.sendall(b"reset\n")
        data = b""
        while True:
            part = s.recv(4096)
            if not part:
                break
            data += part
            if b".\n" in part:
                break
        return data.decode(errors="replace").strip()
    except OSError as e:
        return "ERROR: reset failed (%s)" % e
    finally:
        try:
            s.close()
        except OSError:
            pass


def recover(uri, project_dir=None):
    """Re-upload the project after a board reset wiped the RAM dictionary.
    Runs 'make upload' in the project directory (the same pipeline Terry uses
    from the terminal) so all dependencies are reloaded, then marks the
    editor's history valid again.  Returns a short status string."""
    if project_dir is None:
        # Default to the pn532 project (the LiveCheck bench).
        project_dir = os.path.expanduser("~/fossil/pn532-nfc-reader/src")
    try:
        proc = subprocess.run(
            ["make", "upload"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode == 0:
            mark_all_history_valid()
            return "re-upload OK (%s)" % project_dir
        tail = (proc.stderr or proc.stdout or "").strip()[-200:]
        return "re-upload FAILED: %s" % tail
    except Exception as e:
        return "re-upload ERROR: %s" % e


def run_make(project_dir=None):
    """Run 'make upload' and return BOTH the return code and the full output.
    The output IS the compiler log — every 'ok.', 'not found', 'Redefine',
    'Stack underflow' etc.  F4's LiveCheck parses it to map errors back to the
    source lines in the editor (Terry 2026-08-26: 'LiveCheck is basically
    feeding the errors back to the lines')."""
    if project_dir is None:
        project_dir = os.path.expanduser("~/fossil/pn532-nfc-reader/src")
    try:
        proc = subprocess.run(
            ["make", "upload"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode, proc.stdout or ""
    except Exception as e:
        return -1, "make ERROR: %s" % e


def parse_upload_errors(output):
    """Parse a make-upload reply stream into structured error records.

    The upload compiles the whole chain in one batch; its output contains every
    'ok.' and every error ('not found.', 'is compile-only.', 'Stack underflow',
    'Redefine').  Returns a list of dicts:
      {"word": <offending word or ''>, "message": <clean text>}
    Only REAL errors are returned (not 'ok.' lines, not Redefine warnings —
    those are informational).  Word boundaries are respected so 'error' inside
    a word name (lmt01.error?) or a string does not false-positive (Terry #272).
    """
    errs = []
    for raw in output.splitlines():
        line = strip_ansi(raw).strip()
        if not line:
            continue
        if re.search(r"\bok\.\s*$", line, re.I):
            continue  # a clean compile line — not an error
        if re.search(r"\bRedefine\b", line, re.I):
            continue  # informational — the word compiled, just redefined
        low = line.lower()
        # Only flag lines that carry a real Mecrisp error marker.
        if not any(m in low for m in (
                "not found", "is compile-only", "stack underflow",
                "stack overflow", "not balanced", "wrong address",
                "unhandled interrupt", "invalid", "error", "failed")):
            continue
        word = ""
        m = re.search(r"^[^\s]+", line)
        if m:
            word = m.group(0)
        errs.append({"word": word, "message": line})
    return errs


def livecheck(line, uri=""):
    """Check ONE line on the live bench.  Returns a dict:
      {ok, reply, denied, locked, reset, invalidated, reuploaded, error, line}
    - denied: set when the line uses a flash/danger word (refused, not run)
    - locked: set when the bench gave NO reply (infinite loop)
    - reset:  set when a SWD hardware reset was sent to recover
    - invalidated: set when the Mecrisp boot banner appeared in a reply —
                   the board reset, so the RAM dictionary (and the editor's
                   accumulated green history) is no longer valid
    - reuploaded: set when recover() re-ran 'make upload' to rebuild
    - ok:     True only when the line compiled cleanly
    """
    out = {
        "ok": False,
        "reply": "",
        "denied": None,
        "locked": False,
        "reset": False,
        "invalidated": False,
        "reuploaded": False,
        "error": "",
        "line": line,
    }
    if not is_code_line(line):
        out["ok"] = True  # a comment/blank is trivially fine
        out["reply"] = "(comment/blank — skipped)"
        return out

    # SVD register names (RCC_AHBENR_IOPAEN, GPIOA_MODER_MODER9) are NOT Forth
    # words — gema rewrites them to addresses at upload.  RESOLVE the line
    # through the gema pipeline and send the RESOLVED form to the chip, so the
    # chip checks the real instruction ('if it passes here, upload passes').
    send_line = line
    if contains_svd_name(line):
        resolved = resolve_svd_line(line)
        if resolved is None:
            out["svd_error"] = True
            out["error"] = "could not resolve SVD name via gema — check the register name"
            return out
        out["resolved"] = resolved
        send_line = resolved

    bad = _denied(send_line)
    if bad:
        out["denied"] = bad
        out["error"] = ("'%s' is refused by LiveCheck — it would change flash "
                        "or wipe the dictionary." % bad)
        return out

    # ASSERT CAPABILITY (#274): if the line carries a ( "check": ... ) comment,
    # snapshot the consequence register BEFORE the write so the change-assert
    # can compare (bit flipped? register reached the expected value?).
    check = _parse_check_comment(line)
    before = None
    if check:
        # settle so any previous Forth reply drains before we open the cmd
        # socket — swdd's cmd_handle blocks while the Forth socket is busy,
        # so an immediate read collides (intermittent None).
        time.sleep(0.1)
        _info = _svd_register(check.get("register", ""))
        if _info:
            before = _read_u32(_info[0])

    reply = _fast_run(send_line)
    # Strip ANSI colour codes so every downstream path (banner, error,
    # redefine) shows clean text (#251/#252).
    reply = strip_ansi(reply)
    if not reply or not reply.strip():
        # No reply at all -> the bench is locked in a loop.  A Forth 'reset'
        # word cannot help (the CPU is not executing); use SWD NRST instead.
        out["locked"] = True
        out["reset"] = True
        hw_reset()
        time.sleep(0.5)  # let the reset + boot settle before the next line
        out["reply"] = "(bench locked — sent SWD hardware reset)"
        out["error"] = "bench locked; hardware reset sent via SWD"
        return out

    # GROUND-TRUTH STATE SIGNAL: the Mecrisp boot banner in a reply means the
    # board just reset (Ctrl-C, a crash, cornerstone, a power blip).  The RAM
    # dictionary — everything the editor's green history accumulated — is gone.
    # Invalidate so the LSP re-uploads and re-checks from the top.
    if banner_in_reply(reply):
        out["invalidated"] = True
        invalidate_history(uri)
        out["reply"] = reply
        out["error"] = "board reset detected — RAM dictionary wiped; re-upload needed"
        return out

    out["reply"] = reply
    out["ok"] = line_succeeded(reply)
    # REDEFINE WARNING (Terry 2026-08-24): Mecrisp still returns 'ok.' but
    # prints 'Redefine <word>.' when a word is defined more than once.  Not an
    # error, but on a small chip every redefinition wastes RAM, so flag it as a
    # warning (orange) so Terry knows to clean it up.
    out["redefine"] = bool(out["ok"] and re.search(r"\bredefine\b", reply, re.I))
    if out["ok"]:
        out["error"] = ""
    else:
        # Explain a known Mecrisp error (e.g. 'not found.' -> the typo hint)
        # so the gutter shows the meaning, not just the raw reply.
        out["error"] = reply or "no 'ok.' in reply"
        meaning = explain_error(reply)
        if meaning:
            out["error"] += " — " + meaning

    # ASSERT CAPABILITY (Terry #274): a '( "check": ... )' comment makes the
    # line a test — after it compiles ok, assert the register/bitfield state.
    # e.g.  1 GPIOC_BSRR_BS1 bfs!  ( "check": "GPIOC_ODR", "bit": "ODR1",
    #         "expect": "@regmon" )
    # The change-assert ('@regmon' or omitted) compares the consequence
    # register BEFORE the write (snapshotted above) with AFTER — asserting the
    # bit FLIPPED (works for write-only registers like BSRR).  A hardcoded
    # 'expect' asserts an absolute value.
    if out["ok"] and check:
        out.update(_run_assert(check, before))
    return out


# ---- assert capability (#274) -----------------------------------------------

def _parse_check_comment(line):
    """Extract a ( "check": ... ) assertion from the line's comment.
    Format (Terry #274):  ( "check": "GPIOC_ODR", "bit": "ODR1", "expect": VALUE )
    The register is the value of 'check' itself; 'bit' and 'expect' are extra
    comma-separated keys.  Returns {register, bit, expect} or None."""
    m = re.search(r'\(\s*"check"\s*:\s*(.*?)\)', line)
    if not m:
        return None
    body = m.group(1)
    # the register is the first quoted value right after 'check':
    rm = re.match(r'^\s*"([^"]+)"', body)
    if not rm:
        return None
    d = {"register": rm.group(1)}
    for key in ("bit", "expect"):
        # value may be a quoted string ("ODR1") or a bare token (1, @regmon)
        km = re.search(r'"%s"\s*:\s*("([^"]*)"|([^\s,]+))' % key, body)
        if km:
            d[key] = km.group(2) if km.group(2) is not None else km.group(3)
    return d


def _read_u32(addr):
    """Read a 32-bit word from the chip via the FORTH socket (not the cmd
    socket).  Sending '$<addr> @ .' returns the value in the Forth reply —
    this avoids the cmd-socket/Forth-socket collision that made rapid
    mixed reads fail (the cmd socket wedges while the Forth reply drains)."""
    reply = strip_ansi(_fast_run("$%x @ ." % addr))
    # the reply ends with the decimal value then ' ok.'
    m = re.search(r"\d+\s+ok", reply)
    if m:
        return int(re.search(r"(\d+)\s+ok", reply).group(1))
    return None


# SVD DB lookup for the assert capability (Terry 2026-08-25).  The register
# ADDRESS and BITFIELD POSITION come from the live SVD database — the same one
# Regmon and mecrisp-mcp read — never from a hardcoded local list.  The check
# comment names the register by its compound SVD name (GPIOC_ODR, Flash_CR,
# RCC_CR) and the bit by its field name (ODR1, LOCK, HSIRDY); the magic numbers
# are fetched, not typed.
SVD_DB = site_paths.database("database_rel.db")
_SVD_DB_ALT = [
    site_paths.database("STM32F051.db"),
    site_paths.database("STM32F103.db"),
    site_paths.database("STM32F407.db"),
    site_paths.database("STM32L0xx.db"),
]


def _svd_db_path():
    """First existing SVD DB (the live database_rel.db, else a family DB)."""
    for p in [SVD_DB, *_SVD_DB_ALT]:
        if os.path.isfile(p):
            return p
    return ""


def _svd_parse_addr(text):
    """'$40022010' -> 0x40022010.  Returns None on anything unexpected."""
    if not text:
        return None
    s = str(text).strip()
    if s.startswith("$"):
        s = "0x" + s[1:]
    try:
        return int(s, 16)
    except ValueError:
        return None


def _svd_register(reg_name):
    """Resolve a compound SVD register name ('GPIOC_ODR', 'Flash_CR',
    'RCC_CR') to (addr, peripheral_name, register_name), or None.  The DB
    stores the peripheral and register in separate columns, so the compound
    form is peripheral_name || '_' || name — the same form gema and Regmon
    use.  The peripheral/register names are returned so a bitFIELD can be
    resolved with the same scoping."""
    db = _svd_db_path()
    if not db:
        return None
    try:
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT address, peripheral_name, name FROM register "
            "WHERE (peripheral_name || '_' || name) = ? "
            "OR (lower(peripheral_name) || '_' || lower(name)) = lower(?) "
            "LIMIT 1",
            (reg_name, reg_name)).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    addr = _svd_parse_addr(row[0])
    if addr is None:
        return None
    return (addr, row[1], row[2])


def _svd_bit(periph, reg, bit_field):
    """Resolve a bitfield NAME (LOCK, ODR1, HSIRDY) in a register to its bit
    offset, or None.  Matches by peripheral_name + register_name + field name
    — so 'LOCK' resolves to 7 for Flash_CR without ever knowing the number."""
    db = _svd_db_path()
    if not db:
        return None
    try:
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT bitOffset FROM field "
            "WHERE lower(peripheral_name) = lower(?) "
            "AND lower(register_name) = lower(?) "
            "AND lower(name) = lower(?) LIMIT 1",
            (periph, reg, bit_field)).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _run_assert(check, before):
    """Perform the assert after a line has run.  `before` is the consequence
    register's value snapshotted BEFORE the write.  Returns a dict the caller
    merges into the livecheck result."""
    import time as _time
    reg = check.get("register", "")
    info = _svd_register(reg)
    if info is None:
        return {"assert": "fail", "assert_msg": "unknown register '%s' in check" % reg}
    addr, periph, regname = info
    bit_str = check.get("bit")
    bit = None
    if bit_str:
        # Prefer the SVD field name (LOCK, ODR1, HSIRDY) — the DB resolves it
        # to its bit offset scoped to this exact register.  Fall back to the
        # trailing digits for a raw number or a name not in the DB.
        svd_bit = _svd_bit(periph, regname, bit_str)
        if svd_bit is not None:
            bit = svd_bit
        else:
            m = re.search(r"(\d+)$", bit_str)
            if m:
                bit = int(m.group(1))
            else:
                return {"assert": "fail", "assert_msg": "bad bit '%s'" % bit_str}
    expect = check.get("expect", "@regmon")
    # settle so the Forth socket drains before we read the cmd socket — swdd's
    # cmd_handle blocks while the Forth socket is busy, so an immediate read
    # can collide with the trailing Forth reply (intermittent 'could not read').
    time.sleep(0.1)
    after = _read_u32(addr)
    if after is None:
        return {"assert": "fail", "assert_msg": "could not read %s after write" % reg}
    if bit is None:
        # whole-register assert: hardcoded expect value
        if expect and expect != "@regmon":
            try:
                want = int(expect, 0)
            except ValueError:
                return {"assert": "fail", "assert_msg": "bad expect '%s'" % expect}
            ok = (after == want)
            return {"assert": "pass" if ok else "fail",
                    "assert_msg": "register %s = 0x%X %s 0x%X" % (
                        reg, after, "==" if ok else "!=", want)}
        return {"assert": "pass", "assert_msg": "register %s = 0x%X (no expect)" % (reg, after)}
    # change-assert on a bit: compare before vs after
    b = (before >> bit) & 1 if before is not None else None
    a = (after >> bit) & 1
    if expect and expect != "@regmon":
        try:
            want = int(expect, 0)
        except ValueError:
            return {"assert": "fail", "assert_msg": "bad expect '%s'" % expect}
        ok = (a == want)
        return {"assert": "pass" if ok else "fail",
                "assert_msg": "%s bit %d = %d %s %d" % (reg, bit, a, "==" if ok else "!=", want)}
    if b is None:
        return {"assert": "fail", "assert_msg": "%s bit %d = %d (no before)" % (reg, bit, a)}
    ok = (a != b)
    return {"assert": "pass" if ok else "fail",
            "assert_msg": "%s bit %d: %d -> %d %s" % (reg, bit, b, a,
                                                      "changed" if ok else "UNCHANGED")}


def main():
    """CLI: ./forth_livecheck.py '<forth line>'  (prints JSON)"""
    import json
    import sys
    line = " ".join(sys.argv[1:]).strip()
    if not line:
        print("usage: forth_livecheck.py '<forth line>'")
        return 1
    print(json.dumps(livecheck(line), indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
