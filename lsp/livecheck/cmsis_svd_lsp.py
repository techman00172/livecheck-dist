# pyright: strict

from pygls.lsp.server import LanguageServer
from lsprotocol.types import (
    CompletionItem,
    CompletionList,
    CompletionParams,
    CompletionItemKind,
    InsertTextFormat,
    MarkupKind,
    MarkupContent,
    PublishDiagnosticsParams,
    Diagnostic,
    DiagnosticSeverity,
    Position,
    Range,
    SymbolInformation,
    SymbolKind,
    WorkspaceSymbolParams,
    Location,
)
import logging
import sqlite3
import os
import re
import time
import json
import subprocess
import site_paths

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DEFAULT_DB = os.environ.get(
    "CMSIS_SVD_DB",
    os.path.join(PROJECT_ROOT, "nvim-popup", "furs.db"),
)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename=os.environ.get('CMSIS_SVD_LOG', '/tmp/cmsis-svd.lsp.log'),
    filemode='w'
)
logger = logging.getLogger(__name__)

logger.info("=== CMSIS-SVD LANGUAGE SERVER STARTING ===")

_CMSIS_PATTERN = re.compile(
    r'\b[A-Z][A-Z0-9]{1,6}(?:_[A-Z0-9]{1,}){1,2}[!?@]?\b'
)
_MCU = "unknown"
try:
    mf = os.path.join(PROJECT_ROOT, "Makefile")
    with open(mf) as f:
        for line in f:
            if line.strip().startswith("MCU"):
                _MCU = line.split("=", 1)[1].strip()
                break
except (FileNotFoundError, OSError):
    pass
logger.info(f"MCU: {_MCU}")


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SVDCompletionProvider:
    def __init__(self, db_path: str = "", mcu: str = ""):
        # Explicit CMSIS_SVD_DB env var wins; else resolve by MCU family from
        # the live swdai databases; else fall back to the legacy default.
        env_db = os.environ.get("CMSIS_SVD_DB", "").strip()
        if env_db and os.path.isfile(env_db):
            db_path = env_db
        if not db_path or not os.path.isfile(db_path):
            resolved = self._resolve_db_by_mcu(mcu)
            if resolved:
                db_path = resolved
        if not db_path:
            db_path = DEFAULT_DB
        self.db_path = db_path
        self.mcu = mcu or _MCU
        # ARM-core registers (SysTick, SCB) are NOT in the ST SVD — they live
        # in a separate database with the same schema.  Search both so
        # STK_CSR / SCB_CPUID / etc. complete alongside the ST registers.
        # Resolve relative to the DISTRIBUTION layout first (livecheck-dist/
        # databases), falling back to the development /home/tp layout.
        self.arm_db_path = self._dist_or_dev_db("ARM-Core.db")
        if not os.path.isfile(self.arm_db_path):
            self.arm_db_path = ""
        logger.info(f"Database: {db_path} MCU: {self.mcu} ARM-Core: {self.arm_db_path}")

    @staticmethod
    def _dist_or_dev_db(name: str) -> str:
        """Locate an SVD database via site_paths (distribution databases/
        dir first, else the swdai development checkout).  '' if neither."""
        return site_paths.database(name)

    @staticmethod
    def _resolve_db_by_mcu(mcu: str) -> str:
        """Map an MCU family (e.g. STM32F051xx, STM32F103, F407) to the best
        SVD database (distribution databases/ dir, else swdai dev checkout).
        Returns '' if nothing matches."""
        candidates = [
            "STM32F051-svd.db",
            "STM32F103-svd.db",
            "STM32F407-svd.db",
            "STM32L0xx-svd.db",
            "STM32G030-svd.db",
        ]
        mcu_up = (mcu or "").upper()
        prefer = None
        if mcu_up.startswith("STM32F0") or mcu_up.startswith("F051"):
            prefer = candidates[0]
        elif mcu_up.startswith("STM32F1") or mcu_up.startswith("F103"):
            prefer = candidates[1]
        elif mcu_up.startswith("STM32F4") or mcu_up.startswith("F407"):
            prefer = candidates[2]
        elif mcu_up.startswith("STM32L0") or mcu_up.startswith("L073"):
            prefer = candidates[3]
        elif mcu_up.startswith("STM32G0") or mcu_up.startswith("G030"):
            prefer = candidates[4]
        # Fall back to the first database that actually exists.
        for c in (prefer, *candidates):
            if c:
                p = SVDCompletionProvider._dist_or_dev_db(c)
                if p and os.path.isfile(p):
                    return p
        return ""

    def _search_db(self, db_path: str, like: str):
        """Run the register search against ONE database; return matching rows.

        Returns BOTH the full bitfield names (PERIPH_REG_FIELD) and the
        register-only names (PERIPH_REG) so a whole register can be completed
        as `SysTick_STK_RVR` and not only its bitfields.  Row shape:
        (full_name, desc, bw, bo, reg_name, addr, access).
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # Bitfield rows.
            cursor.execute("""
                SELECT DISTINCT (p.name || '_' || r.name || '_' || f.name) AS full_name,
                       f.description, f.bitWidth, f.bitOffset,
                       r.name AS register_name, r.address, r.access
                FROM field f
                JOIN register r ON f.peripheral_name = r.peripheral_name
                                   AND f.register_name = r.name
                JOIN peripheral p ON f.peripheral_name = p.name
                WHERE (p.name || '_' || r.name || '_' || f.name) LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR f.name LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR r.name LIKE ? ESCAPE '\\' COLLATE NOCASE
                ORDER BY
                    CASE
                        WHEN (p.name || '_' || r.name || '_' || f.name) LIKE ? ESCAPE '\\' THEN 0
                        WHEN r.name LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 1
                        ELSE 2
                    END,
                    p.name,
                    full_name
                LIMIT 300
            """, (like, like, like, like, like))
            results = list(cursor.fetchall())
            # Register-only rows (whole register, no field).
            cursor.execute("""
                SELECT DISTINCT (p.name || '_' || r.name) AS full_name,
                       r.description, NULL AS bitWidth, NULL AS bitOffset,
                       r.name AS register_name, r.address, r.access
                FROM register r
                JOIN peripheral p ON r.peripheral_name = p.name
                WHERE (p.name || '_' || r.name) LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR r.name LIKE ? ESCAPE '\\' COLLATE NOCASE
                ORDER BY
                    CASE
                        WHEN (p.name || '_' || r.name) LIKE ? ESCAPE '\\' THEN 0
                        ELSE 1
                    END,
                    p.name,
                    full_name
                LIMIT 300
            """, (like, like, like))
            results += list(cursor.fetchall())
            conn.close()
            return results
        except sqlite3.Error as e:
            logger.error(f"search error in {db_path}: {e}")
            return []

    def search(self, prefix: str):
        if not prefix:
            return []
        like = f"{_escape_like(prefix)}%"
        results = self._search_db(self.db_path, like)
        # Also search the ARM-core database (SysTick/SCB — not in the ST SVD).
        if self.arm_db_path:
            results += self._search_db(self.arm_db_path, like)
        return results

    def get_peripheral_by_prefix(self, prefix: str):
        """List peripherals matching the prefix.  Searches BOTH the ST SVD db
        and the ARM-core db (SysTick/SCB), so a partial peripheral name is
        found regardless of which database holds it."""
        results = []
        for db_path in (self.db_path, self.arm_db_path):
            if not db_path or not os.path.isfile(db_path):
                continue
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                if not prefix:
                    cursor.execute("SELECT name, description FROM peripheral ORDER BY name LIMIT 100")
                else:
                    like = f"{_escape_like(prefix)}%"
                    cursor.execute("""
                        SELECT name, description FROM peripheral
                        WHERE name LIKE ? ESCAPE '\\' COLLATE NOCASE
                        ORDER BY name LIMIT 50
                    """, (like,))
                results.extend(cursor.fetchall())
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"peripheral error: {e}")
        return results

    def get_registers_for_peripheral(self, periph: str, prefix: str):
        """List registers for a peripheral.  Searches BOTH the ST SVD db and
        the ARM-core db (SysTick/SCB), so STK_CSR etc. appear under SysTick_."""
        results = []
        for db_path in (self.db_path, self.arm_db_path):
            if not db_path or not os.path.isfile(db_path):
                continue
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                if prefix:
                    like = f"{_escape_like(prefix)}%"
                    cursor.execute("""
                        SELECT name, address, access, description FROM register
                        WHERE peripheral_name = ? AND name LIKE ? ESCAPE '\\' COLLATE NOCASE
                        ORDER BY name LIMIT 50
                    """, (periph, like))
                else:
                    cursor.execute("""
                        SELECT name, address, access, description FROM register
                        WHERE peripheral_name = ?
                        ORDER BY name LIMIT 50
                    """, (periph,))
                results.extend(cursor.fetchall())
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"register error: {e}")
        return results

    def get_fields_for_register(self, periph: str, reg: str, prefix: str):
        """List bitfields for a register.  Searches BOTH the ST SVD db and the
        ARM-core db (SysTick/SCB)."""
        results = []
        for db_path in (self.db_path, self.arm_db_path):
            if not db_path or not os.path.isfile(db_path):
                continue
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                like = f"{_escape_like(prefix)}%"
                cursor.execute("""
                    SELECT f.name, f.bitWidth, f.bitOffset, f.description
                    FROM field f
                    WHERE f.peripheral_name = ? AND f.register_name = ? AND f.name LIKE ? ESCAPE '\\' COLLATE NOCASE
                    ORDER BY f.bitOffset
                """, (periph, reg, like))
                results.extend(cursor.fetchall())
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"field error: {e}")
        return results

    def _check_name_in_db(self, db_path: str, name: str):
        """Resolve a dotted CMSIS name against ONE database.

        Returns None if the name is valid there, or an error string.

        Splitting is ambiguous because register names themselves may contain
        underscores (e.g. SysTick's registers are STK_CSR / STK_RVR).  Try the
        longest register tail first:  SysTick_STK_RVR_RELOAD should parse as
        periph=SysTick, reg=STK_RVR, field=RELOAD — NOT reg=STK, field=RVR.
        """
        clean = name.rstrip('!?@')
        parts = clean.split('_')
        if len(parts) < 2:
            return None

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            periph = parts[0]

            # Field first, longest-register interpretation:
            #   periph = parts[0], reg = '_'.join(parts[1:-1]), field = last.
            # A register named with an underscore (STK_RVR) is found because we
            # try reg='STK_RVR' (all middle parts) before the short 'STK'.
            for split_at in range(len(parts) - 1, 1, -1):
                reg = '_'.join(parts[1:split_at])
                field = '_'.join(parts[split_at:])
                if not reg or not field:
                    continue
                cursor.execute(
                    "SELECT 1 FROM field WHERE peripheral_name=? AND register_name=? AND name=? COLLATE NOCASE",
                    (periph, reg, field))
                if cursor.fetchone():
                    return None

            # Register: every part after the peripheral.
            reg = '_'.join(parts[1:])
            cursor.execute(
                "SELECT 1 FROM register WHERE peripheral_name=? AND name=? COLLATE NOCASE",
                (periph, reg))
            if cursor.fetchone():
                return None

            # Peripheral alone.
            cursor.execute(
                "SELECT 1 FROM peripheral WHERE name=? COLLATE NOCASE",
                (periph,))
            if cursor.fetchone():
                return (
                    f"Register/field '{reg}' not found in peripheral {periph} "
                    f"on {self.mcu}. Type {periph}_ and use completions to find valid registers.")
            return (
                f"Peripheral '{periph}' not found "
                f"on {self.mcu}. Type a few characters and use completions to find peripherals.")
        except sqlite3.Error as e:
            logger.error(f"check_name error in {db_path}: {e}")
            return None
        finally:
            conn.close()

    def check_name(self, name: str):
        """Validate a CMSIS name against the ST SVD database AND the ARM-core
        database (SysTick/SCB — not in the ST SVD).  Returns None if valid in
        either, else an error string."""
        # ARM-core names (SysTick, SCB) live in a separate database; the ST
        # database does not know them.  Valid in EITHER => valid.
        verdict = None
        for db_path in (self.db_path, self.arm_db_path):
            if db_path and os.path.isfile(db_path):
                verdict = self._check_name_in_db(db_path, name)
                if verdict is None:
                    return None
        # Neither database recognised the name: report the most specific
        # error found (last one wins — e.g. the ARM db knows the SysTick
        # peripheral even though the ST db reports it 'not found').
        return verdict


completion_provider = SVDCompletionProvider(mcu=_MCU)
json_server = LanguageServer("cmsis-svd-lsp", "v0.1")

# Throttle: min ms between scans per URI
_SCAN_INTERVAL = 0.4
_last_scan = {}
# Per-URI change detection (Terry #250): last-checked content hash per line
# number.  LiveCheck only re-checks a line whose text changed since the last
# scan — unchanged lines keep their previous result, so the chip is not
# hammered on every edit.  Keyed by (uri, line_no) -> hash of the line text.
_last_line_hash = {}
# Per-URI result cache: (uri, line_no) -> (hash, sev, msg).  Unchanged lines
# reuse their last published severity/message so the gutter stays populated.
_last_livecheck_result = {}


def _line_hash(line):
    return hash(line)


def _in_comment(pos: int, line: str) -> bool:
    # Check if position is after a \ (to end of line)
    bs = line.find('\\')
    if bs >= 0 and pos > bs:
        return True
    # Check if position is between ( and )
    depth = 0
    for i, c in enumerate(line[:pos]):
        if c == '(':
            depth += 1
        elif c == ')':
            depth = max(0, depth - 1)
    return depth > 0


# ---------------------------------------------------------------------------
# Bitfield-store operand-order check (bfs! / bfc! family).
#
# The gate-admitted words have a KNOWN stack signature:
#     bfs!  ( value addr bitpos -- )
#     bfc!  ( value addr bitpos -- )
# where the SVD bitfield-name helper (e.g. GPIOA_MODER_MODER9) pushes the
# (addr, bitpos) package and the preceding token supplies the value.  So the
# CORRECT order is:
#     <literal value>  <SVD bitfield name>  bfs!
# e.g.  %10 GPIOA_MODER_MODER9 bfs!
# and the silent failure order is the reversal:
#     GPIOA_MODER_MODER9 %10 bfs!     <- editor accepts, chip misbehaves
# This linter flags the reversal as the user types.  Only words with known
# signatures are checked (no general Forth type inference).
#
# The logic lives in forth_lint.py (pure Python, no pygls) so the mecrisp-mcp
# server — which has no pygls — can reuse it.  The LSP imports it here and
# re-exports the same helpers for the scanner below.
# ---------------------------------------------------------------------------
from forth_lint import (
    _VALUE_CONSTANTS,
    code_tokens as _code_tokens,
    check_bitfield_order as _check_bitfield_order,
    is_literal as _is_literal,
    is_svd_helper as _is_svd_helper,
    check_unknown_words as _check_unknown_words,
    extract_defined_words as _extract_defined_words,
)

# mtime-cached project word set (key=dir, mtime=max sibling mtime, words=set)
_PROJECT_WORDS_CACHE = {"key": None, "mtime": None, "words": set()}


def _project_defined_words(text_doc):
    """Collect the word names this project defines, so the unknown-word check
    doesn't flag them.  Sources: the current document's own definitions PLUS
    every sibling *.fs in the same directory (other project files).  Sibling
    scan is guarded by a short mtime cache so it doesn't re-read on every
    keystroke."""
    import os as _os
    words = set(_extract_defined_words(text_doc.lines))
    doc_path = text_doc.uri[len("file://"):]
    doc_dir = _os.path.dirname(doc_path)
    cache_key = doc_dir
    now = 0
    try:
        entries = _os.listdir(doc_dir)
        for fn in entries:
            if not fn.endswith(".fs"):
                continue
            p = _os.path.join(doc_dir, fn)
            try:
                now = max(now, _os.path.getmtime(p))
            except OSError:
                continue
    except OSError:
        return words
    if (_PROJECT_WORDS_CACHE.get("key") != cache_key
            or _PROJECT_WORDS_CACHE.get("mtime") != now):
        found = set()
        try:
            for fn in entries:
                if not fn.endswith(".fs"):
                    continue
                try:
                    with open(_os.path.join(doc_dir, fn), encoding="utf-8",
                              errors="replace") as f:
                        found |= _extract_defined_words(f)
                except OSError:
                    continue
        finally:
            _PROJECT_WORDS_CACHE["key"] = cache_key
            _PROJECT_WORDS_CACHE["mtime"] = now
            _PROJECT_WORDS_CACHE["words"] = found
    words |= _PROJECT_WORDS_CACHE.get("words", set())
    return words


def _scan_and_publish(ls: LanguageServer, text_doc):
    diagnostics = []
    lines = text_doc.lines
    project_words = _project_defined_words(text_doc)
    for line_no, line in enumerate(lines):
        for m in _CMSIS_PATTERN.finditer(line):
            if _in_comment(m.start(), line):
                continue
            name = m.group()
            msg = completion_provider.check_name(name)
            if msg:
                diagnostics.append(Diagnostic(
                    range=Range(
                        start=Position(line=line_no, character=m.start()),
                        end=Position(line=line_no, character=m.end()),
                    ),
                    severity=DiagnosticSeverity.Warning,
                    source="cmsis-svd-lsp",
                    message=msg,
                ))
        # Bitfield-store operand-order check (bfs!/bfc! family) — flag the
        # reversed "SVD helper then literal" form the editor otherwise accepts.
        for start_col, end_col, msg in _check_bitfield_order(_code_tokens(line)):
            diagnostics.append(Diagnostic(
                range=Range(
                    start=Position(line=line_no, character=start_col),
                    end=Position(line=line_no, character=end_col),
                ),
                severity=DiagnosticSeverity.Warning,
                source="cmsis-svd-lsp",
                message=msg,
            ))
        # Unknown-word SOFT warning: not a literal/SVD helper/dictionary word/
        # project-defined word.  Defers to the chip at upload for ad hoc words.
        for start_col, end_col, msg in _check_unknown_words(
                _code_tokens(line), known_words=project_words):
            diagnostics.append(Diagnostic(
                range=Range(
                    start=Position(line=line_no, character=start_col),
                    end=Position(line=line_no, character=end_col),
                ),
                severity=DiagnosticSeverity.Warning,
                source="cmsis-svd-lsp",
                message=msg,
            ))

    ls.text_document_publish_diagnostics(
        PublishDiagnosticsParams(uri=text_doc.uri, diagnostics=diagnostics))


# ---------------------------------------------------------------------------
# LiveCheck (2026-08-24): live per-line Forth compilation via the bench.
# Each COMPLETED code line is sent to the live chip's compiler over SWD; the
# ok/error is published as a diagnostic in the editor gutter.  Terry's
# invariant: if every previous line compiled ok., the current line's
# dependencies exist — so the per-line ok check IS the dependency check.
# On a locked bench (no reply = infinite loop) a SWD HARDWARE reset (NRST via
# the ST-Link, bypassing the CPU) is sent to recover — a Forth 'reset' word
# cannot help a CPU that is not executing.
# ---------------------------------------------------------------------------
LIVECHECK_ENABLED = True   # master switch (set false to disable LiveCheck)

# OPT-IN + DEPENDS (Terry 2026-08-25).
#
# LiveCheck only chip-checks a file that EXPLICITLY opts in, by putting this
# marker on its first non-blank line:
#     \ #livecheck
# And a file can declare its dependencies are checked FIRST with #depends:
#     \ #depends dependency.fs
# so the dependency files' words are loaded on the chip before this file is
# checked — solving the 'not found' for words defined in other files.  All
# #depends files are in the SAME directory as the scanned file.
#
# The gema-generated files (upload.fs, *_out.fs, source_in.fs) are never
# hand-written, so they are never checked regardless of markers.
_OPTIN_MARKER = "#livecheck"
_DEPENDS_MARKERS = ("#depends", "#depend")  # both spellings accepted (Terry's
                                             # design says #depends; existing
                                             # files use #depend)

# Built-in: generated/compiler-output files that LiveCheck NEVER scans (they
# are produced by the gema pipeline / Makefile, not written by hand, so
# chip-checking them is pointless and often errors — the dictionary state
# never matches the live chip).
_GENERATED_SUFFIXES = ("_out.fs",)
_GENERATED_NAMES = ("upload.fs", "source_in.fs", "summary.md",
                    "summary-fossil.md")


def _is_generated_file(uri):
    name = (uri or "").rsplit("/", 1)[-1].lower()
    if name in _GENERATED_NAMES:
        return True
    for sfx in _GENERATED_SUFFIXES:
        if name.endswith(sfx):
            return True
    return False


def _opt_in_marker(text_doc):
    """The first non-blank line's text, for opt-in detection.  Returns the
    first non-blank line (stripped of a leading backslash), or ''."""
    for ln in getattr(text_doc, "lines", []) or []:
        if not ln.strip():
            continue
        s = ln.lstrip().lstrip("\\").lstrip()
        return s
    return ""


def _is_opted_in(text_doc):
    """Does this file opt in to LiveCheck (first non-blank line has
    '#livecheck')?  Generated files are never checked regardless."""
    if _is_generated_file(getattr(text_doc, "uri", "")):
        return False
    return _OPTIN_MARKER in _opt_in_marker(text_doc)


def _depends_of(text_doc):
    """Collect '#depends <name>' directives from the file.  Returns a list of
    file paths.  All #depends files are in the SAME directory as the scanned
    file (Terry #1), so each is resolved as dir/<name>.  Accepts both the
    '#depends' and '#depend' spellings (existing files use the singular)."""
    import os as _os
    uri = getattr(text_doc, "uri", "")
    if not uri.startswith("file://"):
        return []
    base_dir = _os.path.dirname(uri[len("file://"):])
    depends = []
    for ln in getattr(text_doc, "lines", []) or []:
        s = ln.lstrip().lstrip("\\").lstrip()
        marker = None
        for m in _DEPENDS_MARKERS:
            if m in s:
                marker = m
                break
        if marker is None:
            continue
        rest = s.split(marker, 1)[1].strip()
        name = rest.split()[0] if rest else ""
        if not name:
            continue
        if name.startswith("/"):
            depends.append(name)
        else:
            depends.append(_os.path.join(base_dir, name))
    return depends


def _file_should_check(text_doc):
    """Should LiveCheck chip-check this file?  SIMPLE MODE (Terry 2026-08-26):
    ALWAYS TRUE for any .fs file that isn't generated — the per-line scan runs
    as you edit, no '#livecheck' opt-in marker needed.  Generated files
    (upload.fs, source_in.fs, *_out.fs) are never checked — they are compiler
    output, not hand-written code."""
    if _is_generated_file(getattr(text_doc, "uri", "")):
        return False
    uri = getattr(text_doc, "uri", "")
    return uri.endswith(".fs")


def _publish_with_livecheck(ls, text_doc, force=False, record_only=False):
    """Publish SVD diagnostics + LiveCheck diagnostics together.

    record_only=True (SIMPLE MODE, did_open): record the file's line hashes as
    the baseline WITHOUT sending any line to the chip.  make upload (in the
    terminal) already defined everything — re-sending lines here would REDEFINE
    every word (the Redefine/not-found storm Terry saw).  Only lines the user
    EDITS after open (hash changes) are sent to the chip, so the asserts fire
    on real edits and nothing is redefined.

    force=True bypasses the change-detection cache — every line is re-queried
    against the chip (used after a reset, where the fresh chip state and stale
    cached markers would hide real errors)."""
    import forth_livecheck
    uri = text_doc.uri

    # If the SHELL reset path (F4 -> livecheck-reset.sh) ran, it touched a
    # sentinel because it can't call into this process.  A hardware reset wipes
    # the whole chip, so every open file's history is invalid and the next scan
    # re-uploads from scratch.  NOTE: we only CHECK here (invalidate history) —
    # we must NOT consume the sentinel, or the F4 poller thread never sees it
    # and make (which writes summary.fs) never runs (Terry 2026-08-27).
    if forth_livecheck.reset_pending():
        forth_livecheck.invalidate_all()

    # If a board reset wiped the RAM dictionary (banner seen), the editor's
    # accumulated green history is invalid.  Re-upload the project (make
    # upload) and mark history valid again, then re-check from the top so the
    # diagnostics reflect reality, not a dead state.  SKIPPED in record_only —
    # editing never triggers a re-upload (that is F4's job); the baseline just
    # stays recorded.
    if not record_only and not forth_livecheck.history_valid(uri):
        status = forth_livecheck.recover(uri)
        diags = [Diagnostic(
            range=Range(
                start=Position(line=0, character=0),
                end=Position(line=0, character=0),
            ),
            severity=DiagnosticSeverity.Information,
            source="livecheck",
            message="RAM dictionary reset — %s" % status,
        )]
        ls.text_document_publish_diagnostics(
            PublishDiagnosticsParams(uri=uri, diagnostics=diags))
        return

    # DEPENDS (#1): check #depends dependency files FIRST, so their words
    # are defined on the chip before this file is checked.  Otherwise a line
    # that calls a word defined in another file would falsely report
    # 'not found'.  Only the code lines are sent (no diagnostics published for
    # the dependency files — they are dependencies, not the file being viewed).
    # SKIPPED in record_only (did_open): make upload already loaded the
    # dependencies; re-sending them would redefine words.
    if not record_only:
        for inc_path in _depends_of(text_doc):
            if _is_generated_file("file://" + inc_path):
                continue
            try:
                with open(inc_path) as f:
                    for inc_line in f:
                        inc_line = inc_line.rstrip("\n")
                        if forth_livecheck.is_code_line(inc_line) \
                           and not forth_livecheck.contains_svd_name(inc_line):
                            forth_livecheck.livecheck(inc_line, uri=uri)
            except OSError:
                pass  # a missing depends is harmless — the main scan will flag it

    diags = []
    lines = text_doc.lines
    for line_no, line in enumerate(lines):
        for m in _CMSIS_PATTERN.finditer(line):
            if _in_comment(m.start(), line):
                continue
            name = m.group()
            msg = completion_provider.check_name(name)
            if msg:
                diags.append(Diagnostic(
                    range=Range(
                        start=Position(line=line_no, character=m.start()),
                        end=Position(line=line_no, character=m.end()),
                    ),
                    severity=DiagnosticSeverity.Warning,
                    source="cmsis-svd-lsp",
                    message=msg,
                ))
        for start_col, end_col, msg in _check_bitfield_order(_code_tokens(line)):
            diags.append(Diagnostic(
                range=Range(
                    start=Position(line=line_no, character=start_col),
                    end=Position(line=line_no, character=end_col),
                ),
                severity=DiagnosticSeverity.Warning,
                source="cmsis-svd-lsp",
                message=msg,
            ))
        if not forth_livecheck.is_code_line(line):
            continue
        # Change detection (#250): only re-check a line that CHANGED since the
        # last scan.  Unchanged lines reuse their cached (sev, msg) so the
        # gutter stays populated without hitting the chip again.  EXCEPT when
        # force=True (after livecheck.run) — a fresh upload changed the chip,
        # so every line must be re-verified against the new dictionary.
        lh = _line_hash(line)
        lkey = (uri, line_no)
        cached = _last_livecheck_result.get(lkey)
        if not force and cached is not None and cached[0] == lh:
            _sev, _msg = cached[1], cached[2]
        elif record_only:
            # SIMPLE MODE: this path NEVER sends lines to the chip — it only
            # records the baseline (neutral 'ok' marker).  make upload (F4)
            # already defined every word; re-sending them here would redefine
            # everything.  The chip is only touched by F4 (make) and F5
            # (asserts).  Editing just keeps the baseline fresh.
            _sev = DiagnosticSeverity.Information
            _msg = "ok."
            _last_line_hash[lkey] = lh
            _last_livecheck_result[lkey] = (lh, _sev, _msg)
        else:
            result = forth_livecheck.livecheck(line, uri=uri)
            if result.get("svd_error"):
                # The SVD name could not be resolved via gema — a bad register name.
                _sev = DiagnosticSeverity.Error
                _msg = "SVD resolve error: %s" % result.get("error", "")
            elif result.get("svd_skip"):
                # (legacy) SVD register name — resolved by gema at upload, not a chip
                # word.  Kept for compatibility; modern LiveCheck resolves instead.
                _sev = DiagnosticSeverity.Information
                _msg = "SVD name (checked by cmsis-svd LSP)"
            elif result.get("redefine"):
                # Not an error — the word compiled ok, but was defined more
                # than once (wastes RAM on a small chip).  Orange warning.
                _sev = DiagnosticSeverity.Warning
                _msg = "Redefine"
            elif result.get("ok"):
                # An assert on the line overrides the plain "ok." marker: the
                # line compiled, AND it was a live test.  Show its pass/fail
                # instead of just ok. (Terry #274 — the assert result must
                # reach the gutter, not be dropped).
                if result.get("assert"):
                    if result["assert"] == "pass":
                        _sev = DiagnosticSeverity.Information
                        _msg = "ok. %s" % result.get("assert_msg", "assert pass")
                    else:
                        _sev = DiagnosticSeverity.Error
                        _msg = "ASSERT FAIL: %s" % result.get("assert_msg", "assert failed")
                else:
                    _sev = DiagnosticSeverity.Information
                    _msg = "ok."
            elif result.get("denied"):
                _sev = DiagnosticSeverity.Error
                _msg = "Denied: %s" % result["error"]
            elif result.get("locked"):
                _sev = DiagnosticSeverity.Error
                _msg = "Bench locked — SWD hardware reset sent: %s" % result.get("reply", "")
            elif result.get("invalidated"):
                # The board reset mid-check: history is now invalid, the next scan
                # will re-upload.  Flag it so the editor shows why lines went red.
                _sev = DiagnosticSeverity.Error
                _msg = "Board reset detected — %s" % result.get("error", "")
            else:
                _sev = DiagnosticSeverity.Error
                _msg = "Compile error: %s" % (result.get("error") or "no 'ok.' in reply")
            _last_line_hash[lkey] = lh
            _last_livecheck_result[lkey] = (lh, _sev, _msg)
        sev, msg = _sev, _msg
        # Gutter-only marker: a zero-width diagnostic at the line start (0,0).
        # This shows the per-line sign (check/error) WITHOUT highlighting the
        # text — a full-line range makes Helix render 'bright dots' over spaces
        # that interfere with reading and mouse-copy (Terry #245b).
        diags.append(Diagnostic(
            range=Range(
                start=Position(line=line_no, character=0),
                end=Position(line=line_no, character=0),
            ),
            severity=sev,
            source="livecheck",
            message=msg,
        ))
    ls.text_document_publish_diagnostics(
        PublishDiagnosticsParams(uri=uri, diagnostics=diags))


def _trigger_scan(ls: LanguageServer, text_doc):
    now = time.monotonic()
    last = _last_scan.get(text_doc.uri, 0)
    if now - last >= _SCAN_INTERVAL:
        _last_scan[text_doc.uri] = now
        if LIVECHECK_ENABLED and _file_should_check(text_doc):
            # SIMPLE MODE (Terry 2026-08-26): editing NEVER sends lines to the
            # chip — only records the baseline hash (the SVD static checks in
            # _publish_with_livecheck still run, they are PC-side).  The ONLY
            # things that touch the chip are F4 (make upload + error mapping)
            # and F5 (assert run).  Sending edited lines as you type is what
            # redefined every word on a file that make already uploaded.
            _publish_with_livecheck(ls, text_doc, record_only=True)
        else:
            _scan_and_publish(ls, text_doc)


@json_server.feature("textDocument/didOpen")
def did_open(ls: LanguageServer, params):
    logger.info("=== DOCUMENT OPENED ===")
    text_doc = ls.workspace.get_text_document(params.text_document.uri)
    if LIVECHECK_ENABLED and _file_should_check(text_doc):
        # SIMPLE MODE (Terry 2026-08-26): on OPEN, just record the line hashes
        # as the baseline — do NOT send lines to the chip.  make upload (in the
        # terminal) already defined every word; re-sending them here would
        # redefine everything (the Redefine/not-found storm).  Only lines the
        # user EDITS afterwards are sent (see did_change / _trigger_scan).
        _publish_with_livecheck(ls, text_doc, record_only=True)
    else:
        _scan_and_publish(ls, text_doc)


@json_server.feature("textDocument/didChange")
def did_change(ls: LanguageServer, params):
    text_doc = ls.workspace.get_text_document(params.text_document.uri)
    _trigger_scan(ls, text_doc)


@json_server.command("livecheck.reset")
def livecheck_reset(ls: LanguageServer):
    """workspace/executeCommand: hardware-reset the bench via SWD NRST.

    Usable from ANY LSP-compatible editor (Helix ':lsp-workspace-command',
    Neovim vim.lsp.buf.execute_command, VS Code, ...).  Uses the SWD NRST
    hardware reset (ST-Link drives the reset pin, bypassing the CPU) — NOT
    the Forth 'reset' word, which is useless when Forth is locked up.
    Invalidates all open files' history so the next edit's scan re-uploads
    (make upload) before re-checking."""
    import forth_livecheck
    result = forth_livecheck.hw_reset()
    forth_livecheck.invalidate_all()
    logger.info("livecheck.reset: %s (history invalidated)", result)
    return result


def _dist_or_dev_script(name: str) -> str:
    """Locate a helper script via site_paths (distribution scripts/ dir
    first, else the ~/scripts development location)."""
    return site_paths.script(name)


def _write_and_show_summary(project_dir):
    """Write the project summary from the LIVE chip and pop/refresh the viewer.
    Used by both F4 (after make) and F5 (refresh after running INIT/words) —
    see the livecheck.summary command.  Never breaks the caller on error."""
    import os as _os
    try:
        import project_summary
        paths = project_summary.write_summary(project_dir)
        if paths:
            logger.info("summary: written to %s", ", ".join(paths))
            try:
                viewer = _dist_or_dev_script("summary-tk.sh")
                if not viewer:
                    logger.warning("summary: summary-tk.sh not found (dist or dev)")
                else:
                    subprocess.Popen(
                        [viewer, project_dir],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True)
            except OSError as e:
                logger.warning("summary: viewer launch failed: %s", e)
            return paths
    except Exception as e:
        logger.warning("summary: failed: %s", e)
    return []


@json_server.command("livecheck.summary")
def livecheck_summary(ls: LanguageServer):
    """workspace/executeCommand: refresh the project summary from the LIVE chip
    and pop/refresh the viewer — WITHOUT running make (Terry 2026-08-28).

    F5 is bound to the shell script (summary-refresh.sh) which touches a
    sentinel; this command is the editor-side half.  It re-reads the chip's
    CURRENT state — so after you build (F4) and run a word like `init`, F5
    shows the true post-init registers (e.g. TIM1EN/SPI1EN now enabled), not
    the build-time snapshot."""
    import os as _os
    project_dir = None
    for uri, text_doc in ls.workspace.text_documents.items():
        if uri.endswith(".fs") and not _is_generated_file(uri):
            project_dir = _os.path.dirname(uri[len("file://"):])
            break
    if project_dir is None:
        return json.dumps({"error": "no .fs document open — can't find the project dir"})
    paths = _write_and_show_summary(project_dir)
    return json.dumps({"status": "ok", "summary": paths}, indent=2)


@json_server.command("livecheck.make")
def livecheck_make(ls: LanguageServer):
    """workspace/executeCommand: run 'make upload' and map the compiler errors
    back to the source lines in the editor (Terry 2026-08-26, SIMPLE MODE).

    F4 is bound to the shell script (livecheck-reset.sh) which resets the
    board AND touches the reset sentinel; this command is the editor-side half:
    it runs make, parses the upload output, and publishes each error at the
    offending word's source line — so the errors show in the editor gutter
    instead of only the terminal.  No per-line as-you-type checking.

    Works from any open .fs file's project directory."""
    import forth_livecheck
    import os as _os
    project_dir = None
    for uri, text_doc in ls.workspace.text_documents.items():
        if uri.endswith(".fs") and not _is_generated_file(uri):
            project_dir = _os.path.dirname(uri[len("file://"):])
            break
    if project_dir is None:
        return json.dumps({"error": "no .fs document open — can't find the project dir"})
    rc, output = forth_livecheck.run_make(project_dir)
    forth_livecheck.mark_all_history_valid()
    errs = forth_livecheck.parse_upload_errors(output)
    logger.info("livecheck.make: rc=%s, %d error(s) in %s", rc, len(errs), project_dir)
    _publish_make_errors(ls, errs)
    summary_paths = []
    if rc == 0:
        # F4 = build done = write the summary and pop the viewer (Terry 2026-08-27)
        summary_paths = _write_and_show_summary(project_dir)
    return json.dumps({"status": "ok" if rc == 0 else "errors",
                       "error_count": len(errs),
                       "summary": summary_paths}, indent=2)


def _publish_make_errors(ls, errs):
    """Map make's upload errors to the offending word's SOURCE LINES in each
    open .fs document and publish them (gutter markers).  This is the whole of
    'LiveCheck': read the compiler errors, feed them back to the lines
    (Terry 2026-08-26)."""
    if not errs:
        return
    for uri, text_doc in ls.workspace.text_documents.items():
        if not getattr(text_doc, "uri", "").endswith(".fs"):
            continue
        if _is_generated_file(getattr(text_doc, "uri", "")):
            continue
        lines = getattr(text_doc, "lines", []) or []
        diags = []
        for err in errs:
            word = err.get("word", "")
            if not word:
                continue
            for line_no, ln in enumerate(lines):
                if re.search(r"\b" + re.escape(word) + r"\b", ln):
                    diags.append(Diagnostic(
                        range=Range(
                            start=Position(line=line_no, character=0),
                            end=Position(line=line_no, character=0)),
                        severity=DiagnosticSeverity.Error,
                        source="livecheck",
                        message=err["message"],
                    ))
        if diags:
            ls.text_document_publish_diagnostics(
                PublishDiagnosticsParams(uri=uri, diagnostics=diags))


@json_server.command("livecheck.asserts")
def livecheck_asserts(ls: LanguageServer):
    """workspace/executeCommand: run the ASSERT lines against the built chip
    (Terry 2026-08-26, SIMPLE MODE — F5).

    After make upload defined every word, sends each line carrying a
    ( "check": ... ) assert comment to the chip and publishes pass/fail in the
    gutter.  Assert lines are CALL lines (execute a word) — they do not
    redefine anything.  This is the separate, deliberate assert run: you build
    with F4, then verify the asserts with F5.  Diagnostics are published
    PER-FILE — each assert lands on its own document (a single publish to the
    last file's URI dropped the markers from every other file, Terry
    2026-08-26)."""
    import forth_livecheck
    # per-uri -> list of diagnostics, so each file gets its own publish
    per_uri = {}
    for uri, text_doc in ls.workspace.text_documents.items():
        u = getattr(text_doc, "uri", "")
        if not u.endswith(".fs") or _is_generated_file(u):
            continue
        lines = getattr(text_doc, "lines", []) or []
        for line_no, line in enumerate(lines):
            if not forth_livecheck._parse_check_comment(line):
                continue
            if not forth_livecheck.is_code_line(line):
                continue
            r = forth_livecheck.livecheck(line, uri=u)
            if r.get("assert"):
                if r["assert"] == "pass":
                    sev = DiagnosticSeverity.Information
                    msg = "ok. %s" % r.get("assert_msg", "assert pass")
                else:
                    sev = DiagnosticSeverity.Error
                    msg = "ASSERT FAIL: %s" % r.get("assert_msg", "assert failed")
            elif r.get("ok"):
                sev = DiagnosticSeverity.Information
                msg = "ok."
            else:
                sev = DiagnosticSeverity.Error
                msg = "Compile error: %s" % (r.get("error") or "no 'ok.' in reply")
            per_uri.setdefault(u, []).append(Diagnostic(
                range=Range(start=Position(line=line_no, character=0),
                            end=Position(line=line_no, character=0)),
                severity=sev, source="livecheck", message=msg))
    count = 0
    for u, diag in per_uri.items():
        count += len(diag)
        logger.info("livecheck.asserts: %d diagnostic(s) published to %s",
                    len(diag), u)
        ls.text_document_publish_diagnostics(
            PublishDiagnosticsParams(uri=u, diagnostics=diag))
    return json.dumps({"status": "asserts run", "count": count})


@json_server.feature("textDocument/documentSymbol")
def document_symbol(ls: LanguageServer, params):
    text_doc = ls.workspace.get_text_document(params.text_document.uri)
    logger.info("=== DOCUMENT SYMBOL ===")
    periphs = completion_provider.get_peripheral_by_prefix("")
    symbols = []
    for pname, pdesc in periphs:
        label = f"[SVD] {pname}" + (f" — {pdesc}" if pdesc else "")
        symbols.append(SymbolInformation(
            name=label,
            kind=SymbolKind.Struct,
            location=Location(
                uri=params.text_document.uri,
                range=Range(
                    start=Position(line=0, character=0),
                    end=Position(line=0, character=0),
                ),
            ),
        ))
    return symbols


@json_server.feature("workspace/symbol")
def workspace_symbol(ls: LanguageServer, params: WorkspaceSymbolParams):
    logger.info("=== WORKSPACE SYMBOL ===")
    query = (params.query or "").upper()
    periphs = completion_provider.get_peripheral_by_prefix("")
    symbols = []
    for pname, pdesc in periphs:
        if query and query not in pname.upper():
            continue
        label = f"[SVD] {pname}" + (f" — {pdesc}" if pdesc else "")
        symbols.append(SymbolInformation(
            name=label,
            kind=SymbolKind.Struct,
            location=Location(
                uri="",
                range=Range(
                    start=Position(line=0, character=0),
                    end=Position(line=0, character=0),
                ),
            ),
        ))
    logger.info(f"Returning {len(symbols)} symbols")
    return symbols


def _extract_word(line: str, char_pos: int) -> str:
    if not line or char_pos > len(line):
        return ""
    start = char_pos
    while start > 0:
        c = line[start - 1]
        if not (c.isalnum() or c in {'_', '>', '<', '?', '@', '!'}):
            break
        start -= 1
    return line[start:char_pos]


def _extract_value_prefix(line, char_pos):
    """If the line has a Forth value literal BEFORE the word being completed
    (e.g. '%02 GPIOA_MODER_MODER5'), return the decoded integer + literal text.
    Forth literals: %binary, $hex, decimal, 0x hex.  Returns (int_value,
    literal_text) or (None, '')."""
    before = line[:char_pos]
    # strip the word being typed (the SVD name) — the value is the token
    # immediately before it.  Match a Forth literal at line start or after
    # whitespace, followed by a space + the (partial) word.
    m = re.search(
        r"(^|[\s(])(%[0-9]+|\$[0-9a-fA-F]+|0x[0-9a-fA-F]+|\d+)\s+\S*$",
        before)
    if not m:
        return None, ""
    lit = m.group(2).strip()
    try:
        if lit.startswith("%"):
            # %10 -> binary 2; a leading-zero form like %02 (the user writes
            # the value in decimal-2 style) is read as binary if all digits
            # are 0/1, else as the plain integer.
            digits = lit[1:]
            if set(digits) <= {"0", "1"}:
                return int(digits, 2), lit
            return int(digits, 10), lit
        if lit.startswith("$"):
            return int(lit[1:], 16), lit
        if lit.lower().startswith("0x"):
            return int(lit, 16), lit
        return int(lit, 10), lit
    except ValueError:
        return None, ""


def _decode_bitfield_value(periph, reg, fname, fval):
    """Decode a bitfield VALUE against the RM reference-manual prose value
    table (the '00: Input mode' style lines).  Returns a short string like
    'MODER5 [11:10] = 0x02 Alternate function mode', or None if no decode."""
    # 1. width + offset from the SVD DB (the LSP's normal DB).
    try:
        conn = sqlite3.connect(completion_provider.db_path)
        row = conn.execute(
            "SELECT bitWidth, bitOffset FROM field "
            "WHERE peripheral_name=? AND register_name=? AND name=? LIMIT 1",
            (periph, reg, fname)).fetchone()
        conn.close()
    except Exception:
        row = None
    if not row:
        return None, None
    bw, bo = row[0] or 1, row[1] or 0

    # 2. the value-table prose from the RM DB (the same source Regmon decodes).
    import os as _os
    rm_db = site_paths.database("STM32F051-rm.db")
    if not _os.path.isfile(rm_db):
        return None, None
    prose = None
    try:
        conn = sqlite3.connect(rm_db)
        # try exact field, fall back to the generic 'MODERy' row, then to a
        # SIBLING peripheral (Terry 2026-08-26): the F0 family timers share
        # register layouts, so TIM2_SMCR_ETF's value table is identical to
        # TIM1_SMCR_ETF's — borrow the prose from the sibling when this
        # register wasn't converted yet (the manual is ~36% converted).
        candidates = [periph + "_" + reg]
        if periph.startswith("TIM") and periph[3:].isdigit():
            # same timer type, all number siblings: TIM1<->TIM2<->TIM3,
            # TIM14<->TIM15<->TIM16<->TIM17
            n = int(periph[3:])
            fam = 1 if n in (1, 2, 3) else 2 if n in (14, 15, 16, 17) else None
            sibs = {1: (1, 2, 3), 2: (14, 15, 16, 17)}.get(fam, ())
            candidates += ["TIM%d_%s" % (s, reg) for s in sibs if s != n]
        for cand in candidates:
            row = conn.execute(
                "SELECT description FROM bitfields "
                "WHERE register_name=? AND name=? LIMIT 1",
                (cand, fname)).fetchone()
            if row and row[0] and row[0].strip():
                prose = row[0].strip()
                break
        if not prose:
            # generic-y fallback (MODER0 -> MODERy) on the ORIGINAL register
            generic = ''.join(c for c in fname if not c.isdigit()) + 'y'
            row = conn.execute(
                "SELECT description FROM bitfields "
                "WHERE register_name=? AND name=? LIMIT 1",
                (periph + "_" + reg, generic)).fetchone()
            if row and row[0] and row[0].strip():
                prose = row[0].strip()
        conn.close()
    except Exception:
        return None, None
    if not prose:
        return None, None

    # 3. find the meaning line whose key equals the field value.
    meaning = None
    for line in prose.split("\n"):
        line = line.strip()
        m = re.match(r"^(0b[01]+|0x[0-9a-fA-F]+|[0-9a-fA-F]+):\s*(.+)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        try:
            kval = int(key, 2) if key.startswith("0b") else \
                int(key, 16) if key.startswith("0x") else \
                int(key, 2) if set(key) <= {"0", "1"} else int(key, 16)
        except ValueError:
            continue
        if kval == fval:
            meaning = val
            break
    if meaning is None:
        # No match: either the value is out of range for the field, or the RM
        # table simply has no entry for it.  Flag it honestly instead of
        # silently showing the generic description — a value that doesn't fit
        # a 2-bit field is almost certainly a mistake (e.g. %20 into MODER).
        max_val = (1 << bw) - 1
        if fval > max_val:
            warn = ("value 0x%X does NOT fit this %d-bit field (max 0x%X) — "
                    "check the literal" % (fval, bw, max_val))
        else:
            warn = ("value 0x%X has no meaning defined for this field in the "
                    "RM table" % fval)
        return None, warn
    text = "%s [%d:%d] = 0x%0*X  %s" % (
        fname, bo + bw - 1, bo, (bw + 3) // 4, fval, meaning)
    return text, None


def _build_doc(desc, bw, bo, addr, access, decoded=None, warn=None):
    parts = []
    if decoded:
        parts.append(f"**Live decode:** {decoded}")
    if warn:
        parts.append(f"**WARNING:** {warn}")
    if desc:
        parts.append(f"**Description:** {desc}")
    if bw is not None and bo is not None:
        parts.append(f"**Bit:** {bo}..{bo + bw - 1} (width {bw})")
    if addr:
        parts.append(f"**Address:** {addr}")
    if access:
        parts.append(f"**Access:** {access}")
    return "\n\n".join(parts)


def _apply_field_decode(full_name, line, pos, desc, bw, bo, addr, access):
    """Build the doc for a search-result row (full_name = PERIPH_REG_FIELD or
    PERIPH_REG), adding the LIVE bitfield decode when a value literal precedes
    the SVD name on the line (Terry 2026-08-26).  An unknown/out-of-range value
    is flagged with a warning instead of silently falling back.  Returns
    (doc, short)."""
    decoded = None
    warn = None
    parts = full_name.split("_")
    if len(parts) >= 3:  # PERIPH_REG_FIELD — a bitfield row, decodable
        val, _ = _extract_value_prefix(line, pos)
        if val is not None:
            decoded, warn = _decode_bitfield_value(
                parts[0], parts[1], parts[2], val)
    doc = _build_doc(desc, bw, bo, addr, access, decoded, warn)
    if decoded:
        return doc, decoded
    if warn:
        return doc, "⚠ " + warn
    return doc, (desc or "")[:50]


def _make_item(label, kind_val, detail, doc, insert_text):
    return CompletionItem(
        label="[SVD] " + label,
        kind=kind_val,
        detail=detail or "",
        documentation=MarkupContent(
            kind=MarkupKind.Markdown, value=doc
        ) if doc else None,
        insert_text=insert_text,
        insert_text_format=InsertTextFormat.PlainText,
        filter_text=insert_text,
    )


@json_server.feature("textDocument/completion")
def completion(ls: LanguageServer, params: CompletionParams):
    logger.info("=== COMPLETION ===")
    text_doc = ls.workspace.get_text_document(params.text_document.uri)
    if params.position.line >= len(text_doc.lines):
        return CompletionList(is_incomplete=False, items=[])

    line = text_doc.lines[params.position.line]
    pos = min(params.position.character, len(line))
    # Forth comments: `\` to end of line, `( ... )` inline.  Don't complete
    # register names inside comments.
    if _in_comment(pos, line):
        return CompletionList(is_incomplete=False, items=[])
    raw = _extract_word(line, pos)
    logger.info(f"LINE={line!r} POS={pos} RAW={raw!r}")
    items: list[CompletionItem] = []

    if not raw:
        return CompletionList(is_incomplete=False, items=[])

    if raw.endswith('_'):
        stem = raw[:-1]
        if not stem:
            # Just "_" — list all peripherals
            periphs = completion_provider.get_peripheral_by_prefix("")
            for pname, pdesc in periphs:
                items.append(CompletionItem(
                    label="[SVD] " + pname,
                    kind=None,
                    detail=(pdesc or "")[:50],
                    documentation=None,
                    insert_text=pname,
                    insert_text_format=InsertTextFormat.PlainText,
                    sort_text="!" + pname,
                    filter_text=pname,
                ))
            logger.info(f"Returning {len(items)} peripherals")
            return CompletionList(is_incomplete=False, items=items)
        parts = stem.split('_')

        if len(parts) == 1:
            periph = parts[0]
            regs = completion_provider.get_registers_for_peripheral(periph, "")
            for rname, raddr, raccess, rdesc in regs:
                insert = f"{periph}_{rname}"
                doc = _build_doc(rdesc, None, None, raddr, raccess)
                items.append(_make_item(
                    f"{periph}_{rname}",
                    CompletionItemKind.Constant,
                    (rdesc or "")[:50], doc, insert
                ))

        elif len(parts) == 2:
            periph, reg = parts
            fields = completion_provider.get_fields_for_register(periph, reg, "")
            # If a value literal precedes the SVD name ('%10 GPIOA_MODER_MODER5'),
            # decode the bitfield for that value ('MODER5 [11:10] = 0x02
            # Alternate function mode') so the completion shows what the chip
            # will actually do, not the generic SVD description (Terry
            # 2026-08-26).
            val, val_lit = _extract_value_prefix(line, pos)
            for fname, bw, bo, fdesc in fields:
                insert = f"{periph}_{reg}_{fname}"
                decoded = None
                warn = None
                if val is not None:
                    decoded, warn = _decode_bitfield_value(
                        periph, reg, fname, val)
                doc = _build_doc(fdesc, bw, bo, None, None, decoded, warn)
                short = f"bit {bo}" if bo is not None else ""
                if decoded:
                    short = decoded
                elif warn:
                    short = "⚠ " + warn
                items.append(_make_item(
                    f"{periph}_{reg}_{fname}",
                    CompletionItemKind.Constant,
                    short, doc, insert
                ))

        # 3+ segments typed: user is already at bitfield level, nothing deeper to drill
        # Show completions for the prefix (without trailing _)
        if not items:
            results = completion_provider.search(stem)
            logger.info(f"Deep drill-down search for {raw!r}: {len(results)} results")
            for full_name, desc, bw, bo, reg_name, addr, access in results:
                doc, short = _apply_field_decode(
                    full_name, line, pos, desc, bw, bo, addr, access)
                items.append(CompletionItem(
                    label="[SVD] " + full_name,
                    kind=None,
                    detail=short,
                    documentation=MarkupContent(
                        kind=MarkupKind.Markdown, value=doc
                    ) if doc else None,
                    insert_text=full_name,
                    insert_text_format=InsertTextFormat.PlainText,
                    sort_text=full_name,
                    filter_text=full_name,
                ))

    else:
        periphs = completion_provider.get_peripheral_by_prefix(raw)
        logger.info(f"Exact match check: raw={raw!r}, periphs={[p[0] for p in periphs]}")
        exact = [p for p in periphs if p[0].upper() == raw.upper()]
        logger.info(f"Exact match result: {[p[0] for p in exact]}")
        if exact:
            pname = exact[0][0]
            regs = completion_provider.get_registers_for_peripheral(pname, "")
            for rname, raddr, raccess, rdesc in regs:
                insert = f"{pname}_{rname}"
                doc = _build_doc(rdesc, None, None, raddr, raccess)
                items.append(_make_item(
                    f"{pname}_{rname}",
                    CompletionItemKind.Constant,
                    (rdesc or "")[:50], doc, insert
                ))

        # Append matching peripheral names at the end of the list
        if periphs:
            for pname, pdesc in periphs:
                items.append(CompletionItem(
                    label="[SVD] " + pname,
                    kind=None,
                    detail=(pdesc or "")[:50],
                    documentation=None,
                    insert_text=pname,
                    insert_text_format=InsertTextFormat.PlainText,
                    sort_text="~" + pname,
                    filter_text=pname,
                ))

        # Exact match or matching peripherals: show peripherals + registers, skip flat search flood
        if exact:
            return CompletionList(is_incomplete=False, items=items)

        if not exact and periphs and len(items) >= 5:
            logger.info(f"Matching peripherals exist, skipping flat search flood")
            return CompletionList(is_incomplete=False, items=items)

        results = completion_provider.search(raw)
        logger.info(f"Flat search for {raw!r}: {len(results)} results, first={results[0] if results else None}")
        for full_name, desc, bw, bo, reg_name, addr, access in results:
            doc, short = _apply_field_decode(
                full_name, line, pos, desc, bw, bo, addr, access)
            items.append(CompletionItem(
                label="[SVD] " + full_name,
                kind=None,
                detail=short,
                documentation=MarkupContent(
                    kind=MarkupKind.Markdown, value=doc
                ) if doc else None,
                insert_text=full_name,
                insert_text_format=InsertTextFormat.PlainText,
                sort_text=full_name,
                filter_text=full_name,
            ))

        if not items:
            periphs = completion_provider.get_peripheral_by_prefix(raw)
            for pname, pdesc in periphs:
                items.append(CompletionItem(
                    label="[SVD] " + pname,
                    kind=None,
                    detail=(pdesc or "")[:50],
                    documentation=None,
                    insert_text=pname,
                    insert_text_format=InsertTextFormat.PlainText,
                ))

    # Deduplicate by label.  Multiple completion paths (peripheral match,
    # register drill-down, flat search) can contribute the same bitfield
    # (e.g. RCC_CFGR_PPRE from both the RCC_CFGR register list and the flat
    # search).  Keep the first occurrence, preserve order.
    seen: set[str] = set()
    uniq: list[CompletionItem] = []
    for it in items:
        label = it.label if isinstance(it.label, str) else ""
        if label not in seen:
            seen.add(label)
            uniq.append(it)
    items = uniq

    logger.info(f"Returning {len(items)} items")
    return CompletionList(is_incomplete=False, items=items)


if __name__ == "__main__":
    logger.info("Starting CMSIS-SVD language server...")

    import threading as _threading

    # Sentinel poller (SIMPLE MODE, Terry 2026-08-26): F4's shell script
    # (livecheck-reset.sh) resets the board AND touches a sentinel because it
    # runs outside this process.  F5's script (summary-refresh.sh) and F6's
    # script (livecheck-assert.sh) touch their own sentinels.  This daemon
    # thread watches for all three:
    #   reset sentinel  -> run make + map errors to lines (F4 = reset + build)
    #   summary sentinel -> refresh the summary from the LIVE chip (F5)
    #   assert sentinel -> run the asserts (F6)
    def _sentinel_poller():
        import forth_livecheck
        while True:
            try:
                if forth_livecheck.consume_summary_sentinel():
                    logger.info("sentinel: F5 pressed — refreshing summary")
                    livecheck_summary(json_server)
                if forth_livecheck.consume_assert_sentinel():
                    logger.info("sentinel: F6 pressed — running asserts")
                    livecheck_asserts(json_server)
                if forth_livecheck.consume_reset_sentinel():
                    logger.info("sentinel: F4 pressed — reset + make")
                    livecheck_make(json_server)
            except Exception:
                pass
            time.sleep(0.5)

    _threading.Thread(target=_sentinel_poller, daemon=True).start()

    json_server.start_io()
