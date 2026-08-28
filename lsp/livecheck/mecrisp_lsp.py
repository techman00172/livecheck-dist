# pyright: strict

from pygls.lsp.server import LanguageServer
from lsprotocol.types import (
    Diagnostic,
    DiagnosticSeverity,
    Position,
    Range,
    DidOpenTextDocumentParams,
    CompletionItem,
    CompletionList,
    CompletionParams,
    InsertTextFormat,
    CompletionItemKind,
    MarkupKind,
    MarkupContent,
    MessageType,
    PublishDiagnosticsParams,
    ShowMessageParams
)
import logging
import sqlite3
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename=os.environ.get('MECRISP_LSP_LOG', '/tmp/mecrisp.lsp.log'),
    filemode='w'
)
logger = logging.getLogger(__name__)

logger.info("=== LANGUAGE SERVER STARTING ===")


class MCUCompletionProvider:
    def __init__(self, db_path: str = ""):
        if not db_path:
            db_path = os.path.join(PROJECT_ROOT, "mecrisp_stellaris.db")
        self.db_path = db_path
        logger.info(f"Initializing completion provider with database: {db_path}")
        self._ensure_database_exists()

    def _ensure_database_exists(self):
        if not os.path.exists(self.db_path):
            logger.warning(
                f"Database {self.db_path} not found. "
                "Run: python3 database/setup-mecrisp_stellaris-db.py"
            )
            self._create_sample_database()
        else:
            logger.info(f"Database {self.db_path} exists")
            # ensure the custom-words table exists on a pre-existing database
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS CUSTOM_FORTH(
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        word TEXT UNIQUE NOT NULL,
                        stack TEXT,
                        description TEXT,
                        example TEXT
                    )
                ''')
                conn.commit()
                conn.close()
            except sqlite3.Error:
                pass

    def _create_sample_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE FORTH(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE NOT NULL,
                stack TEXT,
                description TEXT,
                example TEXT
            )
        ''')
        # Custom words (Terry's own, admitted via the words-new test gate) —
        # kept separate from the core FORTH table so the Mecrisp word list
        # stays pristine; the queries UNION both so completions show all.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS CUSTOM_FORTH(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE NOT NULL,
                stack TEXT,
                description TEXT,
                example TEXT
            )
        ''')
        sample_data = [
            ("emit?", "( -- flag )", "Ready to send a character ?", "emit? ."),
            ("key?", "( -- flag )", "Checks if a key is waiting", "key? IF .\" Key!\" THEN"),
            ("key", "( -- char )", "Waits for and fetches the pressed key", "key emit"),
            ("emit", "( char -- )", "Emits a character", "65 emit"),
            ("drop", "( x -- )", "", "123 drop"),
            ("dup", "( x -- x x )", "", "7 dup ."),
            ("swap", "( x1 x2 -- x2 x1 )", "", "1 2 swap . ."),
            ("depth", "( -- +n )", "Gives number of single-cell stack items", "depth ."),
            ("pause", "( -- )", "Task switch, none for default", "pause"),
        ]
        cursor.executemany(
            "INSERT INTO FORTH (word, stack, description, example) VALUES (?, ?, ?, ?)",
            sample_data
        )
        conn.commit()
        conn.close()
        logger.info(f"Created sample database with {len(sample_data)} words")

    def get_all_completions(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT word, stack, description, example FROM FORTH "
                "UNION "
                "SELECT word, stack, description, example FROM CUSTOM_FORTH "
                "ORDER BY word"
            )
            results = cursor.fetchall()
            conn.close()
            logger.info(
                f"Loaded {len(results)} completions from database {self.db_path}"
            )
            return results
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return []

    def search_completions(self, prefix=""):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if prefix:
                escaped = (
                    prefix.replace("\\", "\\\\")
                          .replace("%", "\\%")
                          .replace("_", "\\_")
                )
                cursor.execute(
                    "SELECT word, stack, description, example FROM FORTH "
                    "WHERE word LIKE ? ESCAPE '\\' COLLATE NOCASE "
                    "UNION "
                    "SELECT word, stack, description, example FROM CUSTOM_FORTH "
                    "WHERE word LIKE ? ESCAPE '\\' COLLATE NOCASE "
                    "ORDER BY word",
                    (f"{escaped}%", f"{escaped}%")
                )
            else:
                cursor.execute(
                    "SELECT word, stack, description, example FROM FORTH "
                    "UNION "
                    "SELECT word, stack, description, example FROM CUSTOM_FORTH "
                    "ORDER BY word"
                )

            results = cursor.fetchall()
            conn.close()
            logger.info(
                f"Search for '{prefix}': found {len(results)} results"
            )
            return results
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return []


completion_provider = MCUCompletionProvider()
json_server = LanguageServer("mecrisp-lsp", "v0.1")


@json_server.feature("textDocument/didOpen")
def did_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
    logger.info("=== DOCUMENT OPENED ===")
    text_doc = ls.workspace.get_text_document(params.text_document.uri)
    ls.text_document_publish_diagnostics(
        PublishDiagnosticsParams(uri=text_doc.uri, diagnostics=[])
    )


@json_server.feature("textDocument/completion")
def completion(ls: LanguageServer, params: CompletionParams):
    logger.info("=== COMPLETION REQUEST START ===")
    text_doc = ls.workspace.get_text_document(params.text_document.uri)

    if params.position.line >= len(text_doc.lines):
        return CompletionList(is_incomplete=False, items=[])

    current_line = text_doc.lines[params.position.line]
    char_pos = min(params.position.character, len(current_line))

    # In Forth, `\` comments out the rest of the line and `( ... )` is an
    # inline comment.  Do not offer completions for words inside comments.
    line_before = current_line[:char_pos]
    if '\\' in line_before:
        return CompletionList(is_incomplete=False, items=[])
    depth = 0
    for c in line_before:
        if c == '(':
            depth += 1
        elif c == ')':
            depth = max(0, depth - 1)
    if depth > 0:
        return CompletionList(is_incomplete=False, items=[])

    word_start = char_pos
    while word_start > 0:
        prev_char = current_line[word_start - 1]
        if not (prev_char.isalnum() or prev_char in {'_', '>', '?', '@', '!'}):
            break
        word_start -= 1

    current_word = current_line[word_start:char_pos]

    if current_word:
        results = completion_provider.search_completions(prefix=current_word)
    else:
        results = completion_provider.get_all_completions()

    items = []
    for word, stack, description, example in results:
        doc_parts = []
        if stack:
            doc_parts.append(f"**Stack:** `{stack}`")
        if description:
            doc_parts.append(f"**Description:** {description}")
        if example:
            doc_parts.append(f"**Example:** `{example}`")
        documentation_md = "\n\n".join(doc_parts)

        completion_item = CompletionItem(
            label=word,
            kind=CompletionItemKind.Function,
            detail="",
            documentation=MarkupContent(
                kind=MarkupKind.Markdown,
                value=documentation_md
            ),
            insert_text=word,
            insert_text_format=InsertTextFormat.PlainText,
            sort_text=word,
            filter_text=word
        )
        items.append(completion_item)

    logger.info(f"Returning {len(items)} completion items")
    logger.info("=== COMPLETION REQUEST END ===")
    return CompletionList(is_incomplete=False, items=items)


# ---------------------------------------------------------------------------
# Forth single-step: run the current line on the bench, LSP-orchestrated.
# The editor (Helix, nvim, ...) triggers the custom method 'forth/runLine'
# with the line of Forth; the LSP asks the user (window/showMessageRequest)
# and, on Yes, runs it on the chip and reports success/failure.
# ---------------------------------------------------------------------------
import json


@json_server.feature("forth/runLine")
def run_line(ls: LanguageServer, params):
    """Custom LSP method: params = { line: "..." }.  Asks the user, runs the
    line on the bench, returns { ok, reply, registers, error }."""
    line = ""
    if hasattr(params, "line"):
        line = params.line
    elif isinstance(params, dict):
        line = params.get("line", "")

    if not line or not line.strip():
        return {"ok": False, "reply": "", "error": "empty line"}

    # Ask the user: run this line on the bench?
    from lsprotocol.types import MessageActionItem, ShowMessageRequestParams

    msg = ShowMessageRequestParams(
        type=MessageType.Info,
        message=f"Run this line on the bench?\n\n{line}",
        actions=[
            MessageActionItem(title="Yes"),
            MessageActionItem(title="No"),
        ],
    )
    try:
        answer = ls.show_message_request(msg)
    except Exception:
        answer = None
    if answer is None or answer.title != "Yes":
        return {"ok": False, "reply": "", "error": "cancelled by user"}

    # Run it on the chip
    import forth_single_step
    result = forth_single_step.single_step(line)
    return result


if __name__ == "__main__":
    logger.info("Starting language server...")
    json_server.start_io()
