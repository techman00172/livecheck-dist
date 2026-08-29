#!/usr/bin/env python3
"""project_summary.py — generate a project summary.md after a successful build.

Called by the F4 flow (livecheck_make) after 'make upload' succeeds.  Writes a
'summary.md' into the project directory — a generated MARKDOWN report that is
NEVER in the Makefile (so never built/uploaded).  Terry opens it with
'helix summary.md' as a review buffer.

Markdown (not .fs) was chosen deliberately (Terry 2026-08-27): Forth comments
are rendered dim-grey by the editor, which is useless for a display report.
Markdown gives real colour — headings, bold, and especially TABLES, which are
both more colourful and more informative (aligned Field | Bit | Value | Meaning
columns instead of tree text).  The report is never sent to the chip (it is in
the LSP's _GENERATED_NAMES), so plain data lines are safe.

The summary answers Terry's two questions:
  1. Are there resource problems?   (memory from 'free', register config)
  2. Is the design sane?            (word dependency graph)

REPORT CONTENT:
  MEMORY        'free' output from the chip (flash/RAM used+free), as a table
  CONFIG        key registers (RCC clock) broken into bit-field tables, each
                field with its live value and RM meaning
  DEPENDENCIES  every ': word' with the words it calls; unused words; cycles;
                the most-connected words ('mad woman's breakfast' detector)

If the chip is not reachable the memory/config sections are skipped — the
dependency graph still works (it is pure source analysis).
"""
import os
import re
import socket
import sqlite3

FORTH_SOCK = "/tmp/swdd-forth.sock"
CMD_SOCK = "/tmp/swdd-cmd.sock"
SVD_DB = os.path.expanduser("~/fossil/swdai/database_rel.db")

# Key registers for the CONFIG section.  (peripheral, register) -> why it matters
CONFIG_REGS = [
    ("RCC", "CR"),       # HSI/HSE/PLL on/ready
    ("RCC", "CFGR"),     # clock source + prescalers
    ("RCC", "AHBENR"),   # which peripheral clocks are enabled
    ("RCC", "APB2ENR"),  # APB2 peripherals
    ("RCC", "APB1ENR"),  # APB1 peripherals
]


def _sock_lines(path, cmd):
    """Send a command to a unix socket, return the reply lines."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(path)
        s.sendall((cmd + "\n").encode())
        data = b""
        while True:
            try:
                part = s.recv(4096)
            except socket.timeout:
                break
            if not part:
                break
            data += part
            # Mecrisp ends replies with ' ok.'; the cmd socket closes on EOF.
            # Stop early so the summary never adds a full timeout wait to F4.
            if b" ok" in data or b"ok." in data:
                break
        s.close()
        return data.decode(errors="replace").splitlines()
    except OSError:
        return []


def _forth_free():
    """Run 'free' on the chip, return (region, total, used, free) tuples."""
    lines = _sock_lines(FORTH_SOCK, "free")
    out = []
    for l in lines:
        m = re.search(
            r"(Flash|Ram)\D+(\d+)\D+(\d+)\D+(\d+)", l)
        if m:
            out.append((m.group(1), int(m.group(2)),
                        int(m.group(3)), int(m.group(4))))
    return out


def _svd_addr(periph, reg):
    try:
        conn = sqlite3.connect(SVD_DB)
        row = conn.execute(
            "SELECT address FROM register WHERE peripheral_name=? AND name=?",
            (periph, reg)).fetchone()
        conn.close()
        if row:
            return int(row[0].lstrip("$"), 16)
    except Exception:
        pass
    return None


def _reg_value(addr):
    """Read a 32-bit register via the swdd cmd socket (open-read-close)."""
    if addr is None:
        return None
    lines = _sock_lines(CMD_SOCK, "mem %x 4" % addr)
    for l in lines:
        m = re.search(r":\s*([0-9a-fA-F]{2})\s+([0-9a-fA-F]{2})\s+"
                      r"([0-9a-fA-F]{2})\s+([0-9a-fA-F]{2})", l)
        if m:
            b = [int(g, 16) for g in m.groups()]
            return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)
    return None


def _svd_fields(periph, reg):
    """All bitfields of a register from the SVD DB: [(name, bitOffset,
    bitWidth, description)].  Duplicate field names (SVD + RM source rows)
    collapse to the longest description."""
    try:
        conn = sqlite3.connect(SVD_DB)
        rows = conn.execute(
            "SELECT name, bitOffset, bitWidth, description FROM field "
            "WHERE peripheral_name=? AND register_name=? ORDER BY bitOffset",
            (periph, reg)).fetchall()
        conn.close()
    except Exception:
        return []
    best = {}
    for name, off, wid, desc in rows:
        key = (name, off, wid)
        if key not in best or len(desc or "") > len(best[key] or ""):
            best[key] = desc
    return sorted([(n, o, w, d) for (n, o, w), d in best.items()],
                  key=lambda f: f[1])


def _rm_prose(periph, reg, fname):
    """RM reference-manual prose for a bitfield, with sibling-timer and
    generic fallbacks (same strategy as the LSP's live decode).  Returns the
    prose text or None."""
    rm_db = os.path.expanduser("~/fossil/swdai/databases/stm32f0xx-rm.db")
    if not os.path.isfile(rm_db):
        return None
    try:
        conn = sqlite3.connect(rm_db)
    except Exception:
        return None
    candidates = [periph + "_" + reg]
    if periph.startswith("TIM") and periph[3:].isdigit():
        n = int(periph[3:])
        fam = 1 if n in (1, 2, 3) else 2 if n in (14, 15, 16, 17) else None
        sibs = {1: (1, 2, 3), 2: (14, 15, 16, 17)}.get(fam, ())
        candidates += ["TIM%d_%s" % (s, reg) for s in sibs if s != n]
    prose = None
    try:
        for cand in candidates:
            row = conn.execute(
                "SELECT description FROM bitfields "
                "WHERE register_name=? AND name=? LIMIT 1",
                (cand, fname)).fetchone()
            if row and row[0] and row[0].strip():
                prose = row[0].strip()
                break
        if not prose:
            generic = ''.join(c for c in fname if not c.isdigit()) + 'y'
            row = conn.execute(
                "SELECT description FROM bitfields "
                "WHERE register_name=? AND name=? LIMIT 1",
                (periph + "_" + reg, generic)).fetchone()
            if row and row[0] and row[0].strip():
                prose = row[0].strip()
    finally:
        conn.close()
    return prose


def _rm_meaning(prose, fval, bw):
    """Find the prose value-table line matching fval.  Supports wildcard keys
    ('0xxx', '10xx' — the RM style).  Returns the meaning text, or None if the
    prose has no value table at all (a numeric/calibration field), or an
    honest note if it has a table but the value matches nothing."""
    if not prose:
        return None
    table = []
    for line in prose.split("\n"):
        line = line.strip()
        m = re.match(r"^(0b[01]+|[01x]+|0x[0-9a-fA-F]+):\s*(.+)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if re.fullmatch(r"0b[01]+", key):
            dig, base = key[2:], 2
        elif re.fullmatch(r"0x[0-9a-fA-F]+", key):
            dig, base = key[2:], 16
        else:
            dig, base = key, 2  # binary, may contain x wildcards
        if "x" in dig:
            table.append((dig, None, val))
            continue
        try:
            kval = int(dig, base)
        except ValueError:
            continue
        table.append((dig, kval, val))
    if not table:
        return None  # numeric field (e.g. HSITRIM, HSICAL) — value is the info
    for dig, kval, val in table:
        if "x" not in dig:
            if kval == fval:
                return val
            continue
        # wildcard: match bit by bit, 'x' matches either
        n = len(dig)
        if fval >> n:
            continue  # value wider than the key
        if all(d == "x" or int(d, 2) == ((fval >> (n - 1 - i)) & 1)
               for i, d in enumerate(dig)):
            return val
    max_val = (1 << bw) - 1
    if fval > max_val:
        return f"⚠ value 0x%X does NOT fit this %d-bit field (max 0x%X)" % (
            fval, bw, max_val)
    return "(no meaning defined for value 0x%X in the RM table)" % fval


def _config_section():
    """Read the key registers and emit each bitfield in the compact form
    'Field → meaning' — NO bit range and NO value (Terry 2026-08-27).  Those
    clutter the display; he looks them up in Regmon when he needs them.  A
    field with no RM meaning shows just its name."""
    out = []
    for periph, reg in CONFIG_REGS:
        addr = _svd_addr(periph, reg)
        val = _reg_value(addr)
        fields = _svd_fields(periph, reg)
        full = f"{periph}_{reg}"
        reset = None
        if val is not None:
            try:
                conn = sqlite3.connect(SVD_DB)
                reset = conn.execute(
                    "SELECT resetValue FROM register "
                    "WHERE peripheral_name=? AND name=?",
                    (periph, reg)).fetchone()
                conn.close()
                reset = int(reset[0].lstrip("$"), 16) if reset and reset[0] else None
            except Exception:
                reset = None
        if val is None:
            out.append(f"**{full}**  @ {'`$%X`' % addr if addr else '?'}   "
                       f"*(unreadable)*")
            continue
        out.append(f"**{full}**  @ `{'$%X' % addr}`   "
                   f"live `0x{val:08X}`"
                   + (f"   *(reset `0x{reset:08X}`)*" if reset is not None else ""))
        if not fields:
            out.append("*(no bitfields in SVD for this register)*")
            continue
        for fname, off, wid, desc in fields:
            bw = wid or 1
            fval = (val >> (off or 0)) & ((1 << bw) - 1)
            # value -> meaning from the RM prose
            prose = _rm_prose(periph, reg, fname)
            meaning = _rm_meaning(prose, fval, bw) if prose else None
            if meaning:
                out.append(f"{fname} → {meaning}")
            else:
                # no meaning (numeric field like HSITRIM/HSICAL): show the value
                out.append(f"{fname} = 0x{fval:X}")
        out.append("")
    return out or ["*(chip not reachable — no register info)*"]


_ENABLE_REGS = [("RCC", "AHBENR"), ("RCC", "APB2ENR"), ("RCC", "APB1ENR")]


def _enables():
    """Which peripheral clocks are ENABLED right now?  Reads the three RCC
    clock-enable registers (AHBENR, APB2ENR, APB1ENR) and lists every field
    whose bit is set (its meaning reads '... enabled').  This answers 'are we
    using TIM2?' at a glance — if TIM2EN is set, TIM2 is clocked and in use
    (Terry 2026-08-28)."""
    on, off = [], []
    for periph, reg in _ENABLE_REGS:
        addr = _svd_addr(periph, reg)
        val = _reg_value(addr)
        if val is None:
            continue
        for fname, off_b, wid, desc in _svd_fields(periph, reg):
            if fname.endswith("EN") and not fname.endswith("ENR"):
                bit = 1 << (off_b or 0)
                if val & bit:
                    prose = _rm_prose(periph, reg, fname)
                    meaning = _rm_meaning(prose, 1, 1) if prose else None
                    label = fname[:-2]  # strip the trailing EN
                    on.append((label, meaning or ""))
    if not on:
        return ["*(chip not reachable — no clock-enable info)*"]
    out = []
    for label, meaning in on:
        if meaning:
            out.append(f"- {label}  →  {meaning}")
        else:
            out.append(f"- {label}  →  (enabled)")
    return out


# --- word dependency graph (pure source analysis) ---------------------------
_WORD_DEF_RE = re.compile(r"^\s*:\s+([A-Za-z][A-Za-z0-9.?\-]*)(?=\s|\(|$)")
# tokens that are NOT word calls (numbers, Forth literals, operators)
_NON_WORD = re.compile(
    r"^\d|^[%$#][0-9a-fA-F]+|^0x|^[-+*/=<>.!@]+$|^\(\s*--"
)


def _project_files(project_dir):
    """The real project sources, from the Makefile PROJ_FILES list.  Fall back
    to non-generated .fs files if the Makefile is missing or unclear."""
    mk = os.path.join(project_dir, "Makefile")
    files = []
    try:
        with open(mk, errors="replace") as f:
            text = f.read()
        # PROJ_FILES = src/init.fs src/gpio.fs ... (may span lines with \\)
        m = re.search(r"^PROJ_FILES\s*=\s*(.*?)(?=\n\s*$|\n[A-Z_])", text,
                      re.S | re.M)
        if m:
            raw = m.group(1).replace("\\", " ").replace("$(SRC_DIR)", ".")
            files = [os.path.join(project_dir, p.strip())
                     for p in raw.split() if p.strip().endswith(".fs")]
    except OSError:
        pass
    if files:
        seen, uniq = set(), []
        for f in files:
            if os.path.isfile(f) and f not in seen:
                seen.add(f)
                uniq.append(f)
        return uniq
    # fallback: hand-written .fs only
    return [os.path.join(project_dir, fn)
            for fn in sorted(os.listdir(project_dir))
            if fn.endswith(".fs") and not re.match(
                r"^(upload|source_in|.*_out|summary)\.fs$", fn)]


def _scan_words(project_dir):
    """First pass: find every defined word and the file it lives in.
    Returns (word -> file), ordered."""
    words = {}
    order = []
    for path in _project_files(project_dir):
        try:
            with open(path, errors="replace") as f:
                for line in f:
                    code = line.split("\\", 1)[0].strip()
                    m = _WORD_DEF_RE.match(code)
                    if m:
                        w = m.group(1)
                        if w not in words:
                            words[w] = path
                            order.append(w)
        except OSError:
            continue
    return words, order


def _defs_and_calls(project_dir):
    """Scan the project files -> {word: {called words}}.  Only tokens that
    are DEFINED project words count as calls — so the graph reflects real
    dependencies, not comment noise or built-in words."""
    words, order = _scan_words(project_dir)
    calls = {}
    for path in _project_files(project_dir):
        try:
            with open(path, errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        cur = None
        # walk each definition; the body tokens that are defined words are calls
        for line in text.splitlines():
            code = line.split("\\", 1)[0].strip()
            m = _WORD_DEF_RE.match(code)
            if m:
                cur = m.group(1)
                calls.setdefault(cur, set())
                # one-line definitions: ': name body... ;' — scan the rest
                body = code[m.end():]
                if ";" in body:
                    body = body.split(";", 1)[0]
                for tok in body.split():
                    tok = tok.strip("'\"")
                    if tok in words and tok != cur:
                        calls[cur].add(tok)
                continue
            if cur and code:
                # strip ( stack-effect ) and ( "check" ) comments
                code = re.sub(r"\(\s*\"[^\"]*\"[^)]*\)", "", code)
                code = re.sub(r"\([^)]*\)", "", code)
                for tok in code.split():
                    tok = tok.strip("'\"")
                    if tok in words and tok != cur:
                        calls[cur].add(tok)
    return calls, order


def _word_stack_and_desc(project_dir, word):
    """Find a word's definition and return (stack_effect, description).
    stack_effect: the ( ... -- ... ) right after ': name'.  description: a
    descriptive comment attached to THIS word — on the definition line, or
    the first comment line inside the definition body (before its ';').  A
    trailing comment on the last body line is the strongest signal.  Both
    are best-effort; either may be empty."""
    stack, desc = "", ""
    for path in _project_files(project_dir):
        try:
            with open(path, errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            code = line.split("\\", 1)[0].strip()
            m = _WORD_DEF_RE.match(code)
            if not m or m.group(1) != word:
                continue
            # stack effect: first ( ... ) on the definition line
            rest = code[m.end():]
            sm = re.search(r"\(\s*([^)]*)\)", rest)
            if not sm:
                # stack effect may be on the first body line
                for nxt in lines[i + 1:i + 3]:
                    if re.search(r";", nxt):
                        break
                    sm = re.search(r"\(\s*([^)]*)\)", nxt)
                    if sm:
                        break
            if sm:
                stack = sm.group(1).strip()
            # description: a comment on the definition line, else the LAST
            # comment line inside the body (before ';') — a trailing comment
            # like ' \ ring the piezo for 500ms' is the word's own.
            dm = re.search(r"\\\s+(.+)$", line.rstrip("\n"))
            if dm:
                desc = dm.group(1).strip()
            else:
                for nxt in lines[i + 1:i + 8]:
                    if ";" in nxt:
                        break
                    cm = re.search(r"\\\s+(.+)$", nxt.rstrip("\n"))
                    if cm:
                        desc = cm.group(1).strip()
            return stack, desc
    return stack, desc


def _word_index_section(project_dir):
    """A compact, context-friendly index of every word: name, stack effect,
    one-line description, and what it calls.  This is the AGENT'S map of the
    program — read-once and small enough to fit a limited context window
    (Terry 2026-08-30).  Entry points (words never called) are listed first
    so the program's purpose is visible at a glance."""
    calls, order = _defs_and_calls(project_dir)
    if not order:
        return ["*(no word definitions found)*"]
    defined = set(order)
    called = set()
    for w, deps in calls.items():
        called.update(d for d in deps if d in defined)
    entries = []
    for w in order:
        stack, desc = _word_stack_and_desc(project_dir, w)
        deps = sorted(c for c in calls.get(w, ()) if c in defined and c != w)
        entries.append((w, stack, desc, deps, w not in called))
    entries.sort(key=lambda e: (not e[4], e[0]))  # entry points first
    lines = []
    for w, stack, desc, deps, is_entry in entries:
        tag = "**ENTRY** " if is_entry else ""
        sig = f" `{stack}`" if stack else ""
        note = f" — {desc}" if desc else ""
        calls_txt = f"  →  {', '.join(deps)}" if deps else ""
        lines.append(f"{tag}{w}{sig}{note}{calls_txt}")
    return lines


def _deps_section(project_dir):
    """Build the dependency-graph report (markdown)."""
    calls, order = _defs_and_calls(project_dir)
    if not order:
        return ["*(no word definitions found)*"]
    defined = set(order)
    lines = []
    lines.append(f"**Words defined:** {len(defined)}")
    # the graph: who calls whom (only defined words)
    graph = {}
    for w in order:
        graph[w] = sorted(c for c in calls.get(w, ()) if c in defined and c != w)
    # unused words
    called = set()
    for w, deps in graph.items():
        called.update(deps)
    unused = [w for w in order if w not in called]
    if unused:
        lines.append("**UNUSED words** (defined but never called): " +
                     ", ".join(unused))
    # cycles
    def find_cycle(start):
        seen, path = set(), []

        def dfs(w):
            if w in path:
                return path[path.index(w):] + [w]
            if w in seen:
                return None
            seen.add(w); path.append(w)
            for d in graph.get(w, ()):
                r = dfs(d)
                if r:
                    return r
            path.pop()
            return None
        return dfs(start)
    for w in order:
        c = find_cycle(w)
        if c:
            lines.append("**CYCLE:** " + " -> ".join(c))
            break
    # most-connected
    deg = sorted(graph.items(), key=lambda kv: -len(kv[1]))
    if deg:
        top = deg[0]
        lines.append(f"**Most-connected word:** {top[0]} calls "
                     f"**{len(top[1])}** others "
                     f"({', '.join(top[1][:6])})")
    lines.append("")
    for w in order:
        deps = graph.get(w, [])
        lines.append(f"{w} → {', '.join(deps) if deps else 'none'}")
    return lines


def _summary_data(project_dir):
    """Collect the report data once: (free, config_lines, deps_lines)."""
    return _forth_free(), _config_section(), _deps_section(project_dir)


def generate(project_dir):
    """Generate the Helix-friendly summary.md content for a project.  Returns
    the text.

    Standard GitHub-flavoured markdown: headings, bold, pipe tables.  This is
    the file Terry opens in Helix — the Fossil-wiki flavour (summary-fossil.md)
    is a separate render of the same data (Terry 2026-08-27)."""
    free, config, deps = _summary_data(project_dir)
    L = ["# Project Summary",
         "",
         "Generated by **F4** (make upload, `%s`).  This file is NEVER in the "
         "Makefile — it is a report only, opened as a markdown buffer."
         % __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
         "",
         "---",
         "",
         "## Memory (from the chip, `free`)"]
    if free:
        for region, total, used, fre in free:
            L.append(f"- {region}: total `{total}`  used `{used}`  free `{fre}`")
    else:
        L += ["", "*chip not reachable — no memory info*"]
    L += ["", "**Enables — what's clocked and in use right now:**"]
    L += [""] + _enables()
    L += ["", "---", "", "## Config (key registers)"]
    L += [""] + config
    L += ["---", "", "## Word Dependencies"]
    L += [""] + deps
    L += ["---", "", "## Word Index (agent-friendly, read-once)"]
    L += [""] + _word_index_section(project_dir)
    return "\n".join(L) + "\n"


def generate_fossil(project_dir):
    """Generate the Fossil-wiki summary-fossil.md content for a project.
    Same data as summary.md but written as Fossil Wiki Markdown (the dialect
    the Fossil DCVS wiki renders) — pipe tables work in both, so the content
    is shared; this file is what Terry pastes into a wiki page (Terry
    2026-08-27)."""
    free, config, deps = _summary_data(project_dir)
    L = ["# Project Summary",
         "",
         "Generated by **F4** (make upload, `%s`).  Report only — never in "
         "the Makefile, never built or uploaded."
         % __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
         "",
         "----",
         "",
         "## Memory (from the chip, `free`)"]
    if free:
        for region, total, used, fre in free:
            L.append(f"- {region}: total `{total}`  used `{used}`  free `{fre}`")
    else:
        L += ["", "*chip not reachable — no memory info*"]
    L += ["", "**Enables — what's clocked and in use right now:**"]
    L += [""] + _enables()
    L += ["", "----", "", "## Config (key registers)"]
    L += [""] + config
    L += ["----", "", "## Word Dependencies"]
    L += [""] + deps
    L += ["----", "", "## Word Index (agent-friendly, read-once)"]
    L += [""] + _word_index_section(project_dir)
    return "\n".join(L) + "\n"


def write_summary(project_dir):
    """Write summary.md (Helix flavour) AND summary-fossil.md (wiki flavour)
    into the project dir.  Returns the list of paths written (possibly empty)."""
    written = []
    for name, fn in (("summary.md", generate),
                     ("summary-fossil.md", generate_fossil)):
        try:
            text = fn(project_dir)
        except Exception:
            continue
        path = os.path.join(project_dir, name)
        try:
            with open(path, "w") as f:
                f.write(text)
            written.append(path)
        except OSError:
            continue
    return written


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "."
    path = write_summary(p)
    print("wrote", path)
