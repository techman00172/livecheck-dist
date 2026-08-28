#!/usr/bin/env python3
"""mecrisp-mcp.py — MCP server exposing the Mecrisp-Stellaris Forth dictionary
and the CMSIS-SVD register knowledge base as queryable MCP tools.

WHY THIS EXISTS: the Mecrisp LSP (src/mecrisp_lsp.py) serves completions to an
*editor* (Helix) over stdio.  AI agents (Coder / opencode) are not editors, so
they cannot query it.  Coder answers Forth/register questions from its own KB,
but that is a separate build.  This server reads the SAME source-of-truth
databases the LSP uses and exposes them as MCP tools, so any MCP-capable agent
can look up an authoritative Forth word (stack effect / description / example)
or an SVD register / bitfield directly — no rebuilt knowledge, just a queryable
interface.

TRANSPORT: streamable-http on 127.0.0.1:8792 (LAN-bound, no auth), matching the
forth-gateway pattern so browser/web MCP clients (Qwen page) connect with CORS +
stateless HTTP.  This daemon is READ-ONLY: it never touches the Forth socket or
the chip, so it cannot wedge the ring buffer.

DATABASES (the same source of truth the LSP uses):
  FORTH_DB_DIR   ~/fossil/mecrisp-stellaris-lsp/  ->  mecrisp_stellaris.db
        tables: FORTH (official words) + CUSTOM_FORTH (Terry's gate-approved)
  SVD relational ~/fossil/swdai/database_rel.db
        tables: register(peripheral_name, name, address, resetValue, access,
                         description)
                field(peripheral_name, register_name, name, bitWidth,
                      bitOffset, description)

TOOLS:
  chip_info()                 DB stats (which sources are wired)
  forth_lookup(prefix)        prefix-search Forth words (FORTH UNION CUSTOM_FORTH)
  forth_word(word)            exact lookup of one Forth word
  register_lookup(name)       find SVD register/bitfield by name substring
  register_fields(periph,reg) list the bitfields of one register
  lint_line(line)             lint one Forth line (bfs!/bfc! operand-order check)
  check_svd_name(name)        validate a CMSIS-SVD name against the knowledge base

Usage:
  <venv>/python mecrisp_mcp.py --port 8792
"""
import argparse
import os
import re
import sqlite3

from mcp.server.fastmcp import FastMCP

# Pure-Python lint helpers (no pygls) — shared with cmsis-svd-lsp.
from forth_lint import lint_line as _lint_line_forth
import site_paths as _site_paths

FORTH_DB = _site_paths.lsp_db("mecrisp_stellaris.db")
SVD_DB = _site_paths.database("database_rel.db")

# Which server am I?  register_fields / register_lookup / chip_info exist on
# BOTH mecrisp-mcp (8792) and regmon-mcp (8793).  Every response from those
# shared tools carries a "server" field so an agent can always tell which
# implementation it is talking to (and a test can assert on it).
SERVER_ID = "mecrisp-mcp:8792"


def _tag(obj):
    """Attach the server identity to a response dict (used by shared tools)."""
    return dict(obj, server=SERVER_ID)


# --------------------------------------------------------------------------
# Forth dictionary access (FORTH UNION CUSTOM_FORTH)
# --------------------------------------------------------------------------
def _forth_connect(db_path=FORTH_DB):
    return sqlite3.connect(db_path)


def forth_search(prefix="", limit=200):
    """Return a list of word dicts from FORTH union CUSTOM_FORTH."""
    conn = _forth_connect()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if prefix:
        esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"{esc}%"
        rows = cur.execute(
            "SELECT word, stack, description, example FROM FORTH "
            "WHERE word LIKE ? ESCAPE '\\' COLLATE NOCASE "
            "UNION "
            "SELECT word, stack, description, example FROM CUSTOM_FORTH "
            "WHERE word LIKE ? ESCAPE '\\' COLLATE NOCASE "
            "ORDER BY word LIMIT ?",
            (like, like, limit),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT word, stack, description, example FROM FORTH "
            "UNION "
            "SELECT word, stack, description, example FROM CUSTOM_FORTH "
            "ORDER BY word LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def forth_exact(word):
    """Return the single best match for a word (exact, else prefix unique).
    Defining words are stored in the DB with a ' name' placeholder
    ('variable name', ': name', 'create name'), so a bare 'variable' must
    match 'variable name' too (Terry 2026-08-28)."""
    conn = _forth_connect()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT word, stack, description, example FROM FORTH "
        "WHERE word = ? COLLATE NOCASE "
        "UNION "
        "SELECT word, stack, description, example FROM CUSTOM_FORTH "
        "WHERE word = ? COLLATE NOCASE",
        (word, word),
    ).fetchall()
    if not rows and word and not word.endswith(" name"):
        # defining words are stored as '<word> name' — match the bare form
        rows = cur.execute(
            "SELECT word, stack, description, example FROM FORTH "
            "WHERE word = ? COLLATE NOCASE "
            "UNION "
            "SELECT word, stack, description, example FROM CUSTOM_FORTH "
            "WHERE word = ? COLLATE NOCASE",
            (word + " name", word + " name"),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# SVD register / bitfield access
# --------------------------------------------------------------------------
def register_search(name, limit=50):
    """Find registers/bitfields matching a name substring.  Returns a list of
    records: register matches (with address + description) and field matches."""
    if not name or not name.strip():
        return {"error": "name required"}
    term = f"%{name.strip()}%"
    conn = sqlite3.connect(SVD_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Registers are stored with a separate peripheral_name column (name='OTYPER'
    # for GPIOC).  Match both forms: the bare name ('OTYPER') and the compound
    # form the user types ('GPIOC_OTYPER' = peripheral_name || '_' || name).
    # Use the concatenated column for the compound match.
    regs = cur.execute(
        "SELECT peripheral_name, name, address, resetValue, access, description "
        "FROM register "
        "WHERE peripheral_name LIKE ? OR name LIKE ? "
        "OR (peripheral_name || '_' || name) LIKE ? "
        "ORDER BY peripheral_name, name LIMIT ?",
        (term, term, term, limit),
    ).fetchall()

    fields = cur.execute(
        "SELECT peripheral_name, register_name, name, bitWidth, bitOffset, description "
        "FROM field WHERE name LIKE ? OR register_name LIKE ? "
        "OR (peripheral_name || '_' || register_name) LIKE ? "
        "OR (peripheral_name || '_' || register_name || '_' || name) LIKE ? "
        "ORDER BY peripheral_name, register_name, bitOffset LIMIT ?",
        (term, term, term, term, limit),
    ).fetchall()

    # Only fetch fields if the name matches a register exactly enough — avoid
    # dumping thousands of fields for a broad match.
    conn.close()
    return {
        "registers": [dict(r) for r in regs],
        "fields": [dict(r) for r in fields],
    }


def _register_fields_lookup(peripheral, register, limit=200):
    """List all bitfields of one specific register (peripheral.register)."""
    conn = sqlite3.connect(SVD_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Accept either "GPIOC_MODER" style or (peripheral="GPIOC", register="MODER")
    if not peripheral and register and ("." in register or "_" in register):
        parts = re.split(r"[._]", register, maxsplit=1)
        peripheral, register = parts[0], parts[1]
    if not register:
        return {"error": "register name required"}
    rows = cur.execute(
        "SELECT name, bitWidth, bitOffset, description FROM ("
        "  SELECT name, bitWidth, bitOffset, description, "
        "         MAX(LENGTH(description)) AS dlen "
        "  FROM field "
        "  WHERE peripheral_name = ? AND register_name = ? "
        "  GROUP BY name, bitWidth, bitOffset "
        "  ORDER BY bitOffset"
        ") ORDER BY bitOffset LIMIT ?",
        (peripheral or "", register, limit),
    ).fetchall()
    conn.close()
    return {"peripheral": peripheral, "register": register,
            "fields": [dict(r) for r in rows]}


# --------------------------------------------------------------------------
# MCP server
# --------------------------------------------------------------------------
def build_mcp(host="127.0.0.1", port=8792):
    mcp = FastMCP(
        "mecrisp-mcp",
        host=host,
        port=port,
        instructions=(
            "Read-only knowledge base for Mecrisp-Stellaris Forth (STM32F051) "
            "and the CMSIS-SVD register set.  Look up a Forth word's stack "
            "effect / description / example, or a chip register / bitfield's "
            "address and meaning.  This never touches the live chip or the "
            "Forth socket — it answers purely from the authoritative SQLite "
            "databases."
        ),
    )
    # Stateless HTTP so browser MCP clients don't need Mcp-Session-Id.
    mcp.settings.stateless_http = True

    @mcp.tool()
    def chip_info() -> str:
        """Report the wired knowledge sources (database paths + row counts)."""
        import json
        info = {"forth_db": FORTH_DB, "svd_db": SVD_DB}
        try:
            c = sqlite3.connect(FORTH_DB)
            info["forth_words"] = c.execute("SELECT count(*) FROM FORTH").fetchone()[0]
            info["custom_words"] = c.execute("SELECT count(*) FROM CUSTOM_FORTH").fetchone()[0]
            c.close()
        except sqlite3.Error as e:
            info["forth_error"] = str(e)
        try:
            c = sqlite3.connect(SVD_DB)
            info["registers"] = c.execute("SELECT count(*) FROM register").fetchone()[0]
            info["fields"] = c.execute("SELECT count(*) FROM field").fetchone()[0]
            c.close()
        except sqlite3.Error as e:
            info["svd_error"] = str(e)
        return json.dumps(_tag(info), indent=2)

    @mcp.tool()
    def forth_lookup(prefix: str = "", limit: int = 50) -> str:
        """Prefix-search the Mecrisp Forth dictionary (official FORTH words
        plus Terry's CUSTOM_FORTH).  Returns matching words with their stack
        effect, description and example.  Empty prefix lists all.
        Example: forth_lookup('ms.')  ->  words that start with 'ms.'"""
        import json
        return json.dumps(forth_search(prefix, limit), indent=2)

    @mcp.tool()
    def forth_word(word: str) -> str:
        """Exact lookup of one Mecrisp Forth word by name.  Returns the stack
        effect, description and example for that word (or an empty list if
        the word is not in the database).
        Example: forth_word('emit')  ->  emit's definition."""
        import json
        return json.dumps(forth_exact(word), indent=2)

    @mcp.tool()
    def register_lookup(name: str) -> str:
        """Search the CMSIS-SVD register/bitfield knowledge base by name
        (substring, case-insensitive).  Returns matching registers (with
        peripheral, address, reset value, description) and bitfields.
        Example: register_lookup('IOPCEN') or register_lookup('GPIOA_OTYPER')."""
        import json
        return json.dumps(_tag(register_search(name)), indent=2)

    @mcp.tool()
    def register_fields(peripheral: str = "", register: str = "") -> str:
        """List every bitfield of one register.  Pass either a combined name
        ('GPIOC_MODER') or peripheral + register ('GPIOC', 'MODER').
        Example: register_fields(register='GPIOC_MODER') or
                 register_fields('GPIOC', 'MODER')."""
        import json
        return json.dumps(_tag(_register_fields_lookup(peripheral, register)), indent=2)

    @mcp.tool()
    def lint_line(line: str, known_words: str = "") -> str:
        """Lint ONE line of Forth against the gate-verified stack signatures.
        Flags reversed operand order on bfs!/bfc! (which expect
        'value addr bitpos'): the SVD bitfield name must come BEFORE the
        value.  e.g. lint_line('GPIOA_MODER_MODER1 ANALOG bfs!') -> a warning;
        lint_line('ANALOG GPIOA_MODER_MODER1 bfs!') -> clean.  ALSO soft-flags
        tokens that are not in the Mecrisp dictionary DB, not a literal/SVD
        name, and not in known_words (a comma-separated list of words the
        project defines — pass them so your own words aren't flagged).
        Knows the build-time value constants (OUTPUT/ANALOG/AF2...) from
        constants.pat.  Returns a JSON list of {start, end, message}
        (empty = clean)."""
        import json
        diags = []
        known = [w.strip() for w in known_words.split(",") if w.strip()]
        for start, end, msg in _lint_line_forth(line, known_words=known):
            diags.append({"start": start, "end": end, "message": msg})
        return json.dumps(diags, indent=2)

    @mcp.tool()
    def check_svd_name(name: str) -> str:
        """Validate a CMSIS-SVD name (e.g. 'GPIOA_MODER_MODER9',
        'RCC_AHBENR', 'GPIOC_OTYPER') against the SVD knowledge base.  Returns
        {'valid': true} or {'valid': false, 'error': ...}.  Same check the
        cmsis-svd-lsp runs in the editor, available to agents before upload."""
        import json
        clean = name.strip().rstrip("!?@")
        if not clean:
            return json.dumps({"valid": False, "error": "empty name"})
        conn = sqlite3.connect(SVD_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        parts = clean.split("_")
        try:
            if len(parts) < 2:
                conn.close()
                return json.dumps({"valid": False,
                                   "error": f"'{name}' is not a CMSIS name "
                                            "(need PERIPH_REG[_FIELD])"})
            periph = parts[0]
            # Field: periph = parts[0], reg = middle, field = last.  Try the
            # longest register tail first (SysTick_STK_RVR_RELOAD etc.).
            for split_at in range(len(parts) - 1, 1, -1):
                reg = "_".join(parts[1:split_at])
                field = "_".join(parts[split_at:])
                if not reg or not field:
                    continue
                row = cur.execute(
                    "SELECT 1 FROM field WHERE peripheral_name=? AND "
                    "register_name=? AND name=? COLLATE NOCASE",
                    (periph, reg, field),
                ).fetchone()
                if row:
                    return json.dumps({"valid": True})
            # Register: every part after the peripheral.
            reg = "_".join(parts[1:])
            row = cur.execute(
                "SELECT 1 FROM register WHERE peripheral_name=? AND name=? "
                "COLLATE NOCASE",
                (periph, reg),
            ).fetchone()
            if row:
                return json.dumps({"valid": True})
            # Peripheral alone.
            row = cur.execute(
                "SELECT 1 FROM peripheral WHERE name=? COLLATE NOCASE",
                (periph,),
            ).fetchone()
            if row:
                return json.dumps({"valid": False,
                                   "error": f"register/field '{reg}' not found "
                                            f"in peripheral {periph}"})
            return json.dumps({"valid": False,
                               "error": f"peripheral '{periph}' not found"})
        finally:
            conn.close()

    return mcp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--forth-db", default=FORTH_DB)
    ap.add_argument("--svd-db", default=SVD_DB)
    args = ap.parse_args()

    mcp = build_mcp(host="127.0.0.1", port=args.port)
    try:
        import uvicorn
        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware

        starlette_app = mcp.streamable_http_app()
        starlette_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )
        config = uvicorn.Config(
            starlette_app,
            host="127.0.0.1",
            port=args.port,
            log_level="info",
        )
        uvicorn.Server(config).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
