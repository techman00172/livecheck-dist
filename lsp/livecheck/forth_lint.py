#!/usr/bin/env python3
"""forth_lint.py — pure, pygls-free Forth linting helpers.

Shared by two consumers:
  * cmsis-svd-lsp (src/cmsis_svd_lsp.py)  — editor diagnostics (needs pygls)
  * mecrisp-mcp (src/mecrisp_mcp.py)      — MCP lint tools (has NO pygls)

The checks are pure Python (re, os, sqlite3) so they live HERE, not in a
pygls module.  Either consumer imports this file; neither drags the other's
dependencies in.

Operand-order rule (gate-verified):
    bfs!  ( value addr bitpos -- )
    bfc!  ( value addr bitpos -- )
The SVD bitfield-name helper (GPIOA_MODER_MODER9) pushes the (addr, bitpos)
package; the preceding token supplies the value.  Correct order:
    <value literal/constant>  <SVD bitfield name>  bfs!
    e.g.  %10 GPIOA_MODER_MODER9 bfs!
The silent-failure reversal is flagged:
    GPIOA_MODER_MODER9 %10 bfs!     <- editor accepts, chip misbehaves

Unknown-word check (Terry 2026-08-28): a token that is NOT a numeric
literal, NOT an SVD helper, NOT in the Mecrisp dictionary DB
(mecrisp_stellaris.db — the SAME database the editor LSP and mecrisp-mcp
read), and NOT a known project word is flagged as a SOFT WARNING.  The chip
at upload is the final judge — ad hoc words defined live on silicon can't be
in the static DB, so this check defers to F4 rather than hard-erroring.
"""
import os
import re
import sqlite3

_BITFIELD_STORE_SIGS = {
    "bfs!": "( value addr bitpos -- )",
    "bfc!": "( value addr bitpos -- )",
}
_SVD_HELPER_RE = re.compile(r'[A-Z][A-Z0-9]{1,6}(?:_[A-Z0-9]{1,}){1,2}[!?@]?')

# Value-constant names from the gema build's constants.pat (the SAME source
# gema uses to resolve names like OUTPUT/ANALOG/AF2 at build time).  A token
# that matches one of these is a VALUE operand, not an SVD helper name — so
# `GPIOA_MODER_MODER1 ANALOG bfs!` (old convention) is recognised as
# name-then-value and flagged.
_VALUE_CONSTANTS = set()
import site_paths as _site_paths
_CONSTANTS_PAT = _site_paths.pattern("constants.pat")


def _load_value_constants():
    """Parse constants.pat: every 'NAME=value' line contributes NAME (the
    build-time value constant).  Only BITFIELD-VALUE constants are kept —
    those whose value is %binary or a small decimal (OUTPUT=%01, AF2=%0010,
    PUSH-PULL=0).  Register-ADDRESS constants (SCB_CPUID=0xE000ED00 etc.) are
    not bitfield values and are excluded.  Returns a set of names."""
    names = set()
    try:
        with open(_CONSTANTS_PAT) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("!"):
                    continue
                if "=" not in line:
                    continue
                name, _, val = line.partition("=")
                name = name.strip()
                val = val.strip().split("!")[0].strip()  # drop inline comment
                if not name:
                    continue
                if val.startswith("%") or val in ("0", "1"):
                    names.add(name)
    except OSError:
        pass
    return names


def is_literal(tok: str) -> bool:
    """Is this token a VALUE operand for a bitfield word?  True for numeric
    literals (%10, $20, 0x1F, 1) and for build-time value constants
    (OUTPUT, ANALOG, AF2, PUSH-PULL ...) from the gema constants.pat."""
    if not tok:
        return False
    if tok[0] in '%$':
        return True
    if tok[:2].lower() == '0x':
        return True
    if all(c in '0123456789' for c in tok):
        return True
    return tok in _VALUE_CONSTANTS


def is_svd_helper(tok: str) -> bool:
    """Is this token an SVD bitfield-name helper (pushes addr+bitpos)?"""
    return bool(_SVD_HELPER_RE.fullmatch(tok))


# ---------------------------------------------------------------------------
# Mecrisp dictionary lookup (the SAME mecrisp_stellaris.db the editor LSP and
# mecrisp-mcp read).  Loaded once at import into a plain set of words.
# Defining words are stored in the DB as 'WORD name' (e.g. 'variable name',
# ': name', 'create name') — the ' name' is a placeholder for the name the
# defining word consumes.  Strip it so 'variable', ':' and 'create' match.
# ---------------------------------------------------------------------------
_DICT_DB = _site_paths.lsp_db("mecrisp_stellaris.db")


def _load_dictionary_words():
    """Return the set of valid Mecrisp word names (FORTH UNION CUSTOM_FORTH),
    with the placeholder suffix stripped from defining/parsing words
    ('variable name' -> 'variable', 'char *' -> 'char').  Falls back to an
    empty set if the DB is missing so the linter never crashes."""
    words = set()
    try:
        conn = sqlite3.connect(_DICT_DB)
        cur = conn.cursor()
        cur.execute(
            "SELECT word FROM FORTH "
            "UNION "
            "SELECT word FROM CUSTOM_FORTH")
        for (w,) in cur.fetchall():
            w = w.strip()
            if not w:
                continue
            words.add(w)
            for placeholder in (" name", " *"):
                if w.endswith(placeholder):
                    words.add(w[:-len(placeholder)])
        conn.close()
    except sqlite3.Error:
        pass
    return words


_DICT_WORDS = _load_dictionary_words()


def is_dictionary_word(tok: str) -> bool:
    """Is this token a known Mecrisp dictionary word (or custom word)?"""
    return tok in _DICT_WORDS


# Defining words whose NEXT token is the new word's name.  ':' defines a
# colon word; variable/constant/create/2variable... define a named entity.
_DEFINING_WORDS = frozenset({
    ":", "variable", "2variable", "nvariable", "constant", "2constant",
    "create", "buffer:", "fvariable", "variable",
})


def extract_defined_words(lines):
    """Scan source lines and return the set of word names the project DEFINES
    (after ':' 'variable' 'create' 'constant' ...).  Used so the linter's
    unknown-word check doesn't flag a project's own words (Terry 2026-08-28).
    Accepts an iterable of lines OR a multi-line string."""
    defined = set()
    if isinstance(lines, str):
        lines = lines.splitlines()
    for line in lines:
        tokens = code_tokens(line)
        for idx, (tok, _start) in enumerate(tokens):
            if tok in _DEFINING_WORDS and idx + 1 < len(tokens):
                name = tokens[idx + 1][0]
                # a stack-effect comment or literal right after ':' is not a name
                if name and not is_literal(name) and not is_svd_helper(name):
                    defined.add(name)
    return defined


def code_tokens(line: str):
    """Split a Forth line into (token, start_col) for code only — comments
    (backslash to EOL, parenthesised inline) are stripped.  String literals
    (." ..." and s" ...") are consumed whole so their contents are NOT
    tokenised as words.  Returns a list."""
    tokens = []
    i, n = 0, len(line)
    depth = 0
    while i < n:
        c = line[i]
        if c == '\\':
            break
        if c == '(':
            depth += 1
            i += 1
            continue
        if c == ')':
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth > 0 or c.isspace():
            i += 1
            continue
        start = i
        # A string-opening word (." s" c") swallows everything to the closing
        # quote so the literal's contents never look like words.
        if line[i:i + 2] in ('."', 's"', 'c"', '.(', '("'):
            j = line.find('"', i + 2)
            if j == -1:
                j = n
            else:
                j += 1
            tokens.append((line[start:j], start))
            i = j
            continue
        while i < n and not line[i].isspace() and line[i] not in '()':
            i += 1
        tokens.append((line[start:i], start))
    return tokens


def _is_string_literal(tok: str) -> bool:
    """Is this token a whole string literal (." ..." s" ..." c" ...")?"""
    return tok[:2] in ('."', 's"', 'c"', '.(')


def check_unknown_words(tokens, known_words=None):
    """Return a list of (start_col, end_col, message) diagnostics for tokens
    that are NOT a known dictionary word, a literal, an SVD helper, or a word
    the project itself defines (known_words).  SOFT WARNING only — the chip at
    upload is the final judge, so ad hoc words on silicon are the caller's
    responsibility, not a hard error here.  Empty list = no problem."""
    known = _DICT_WORDS
    if known_words:
        known = set(known) | set(known_words)
    diags = []
    for tok, start in tokens:
        if is_literal(tok) or is_svd_helper(tok) or _is_string_literal(tok):
            continue
        if tok in known:
            continue
        diags.append((
            start,
            start + len(tok),
            f"'{tok}' is not in the Mecrisp dictionary DB — if it's a word "
            f"you defined (in this file, another project file, or live on "
            f"the chip) that's fine; otherwise it will fail at upload.",
        ))
    return diags


def check_bitfield_order(tokens):
    """Return a list of (start_col, end_col, message) diagnostics for reversed
    operand order on known bitfield-store words.  Empty list = no problem."""
    diags = []
    for idx, (tok, start) in enumerate(tokens):
        if tok not in _BITFIELD_STORE_SIGS or idx < 2:
            continue
        prev_tok, _prev_start = tokens[idx - 1]
        prev2_tok, prev2_start = tokens[idx - 2]
        # Correct: <value literal> <SVD helper> <word>
        if is_svd_helper(prev_tok) and is_literal(prev2_tok):
            continue
        # Reversed: <SVD helper> <value literal> <word>
        if is_literal(prev_tok) and is_svd_helper(prev2_tok):
            sig = _BITFIELD_STORE_SIGS[tok]
            diags.append((
                prev2_start,
                start + len(tok),
                f"Reversed operand order for {tok} (expected {sig}): "
                f"value literal first, then the SVD bitfield name, then {tok}. "
                f"e.g. %10 GPIOA_MODER_MODER9 {tok}",
            ))
    return diags


def lint_line(line: str, known_words=None):
    """Lint one Forth line: returns a list of (start_col, end_col, message)
    diagnostics for that line — operand-order errors PLUS soft unknown-word
    warnings (a token that is not a literal, SVD helper, dictionary word or
    project-defined word).  Empty list = clean.

    known_words: optional iterable of words this project defines (from other
    files or the same file) so they are not flagged as unknown."""
    tokens = code_tokens(line)
    diags = check_bitfield_order(tokens)
    diags.extend(check_unknown_words(tokens, known_words))
    return diags


# Load the value-constant names from the build's constants.pat once at import.
_VALUE_CONSTANTS = _load_value_constants()


if __name__ == "__main__":
    # Quick self-test.
    import sys
    for line in sys.argv[1:]:
        d = lint_line(line)
        print(("FLAG" if d else "clean"), line, d if d else "")
