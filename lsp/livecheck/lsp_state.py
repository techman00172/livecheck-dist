#!/usr/bin/env python3
"""lsp_state.py — snapshot the cmsis-svd LSP's live view to a JSON file.

The AI (opencode) can't reach into Helix — no editor control socket.  But the
LSP already HAS the live truth: every open document's current contents
(including unsaved edits, from didOpen/didChange) and the diagnostics it
publishes to the gutter.  This module lets the LSP write that state to a
small JSON file which a thin MCP server reads back to the AI.

This is the "without fighting Helix" trick: we don't drive the editor, we
read what the editor already told the LSP.

The LSP calls snapshot() after every publish; the MCP server reads
/tmp/livecheck-lsp-state.json.
"""
import json
import os
import time

SNAPSHOT_PATH = "/tmp/livecheck-lsp-state.json"


def _diag_to_dict(d):
    """Convert a pygls Diagnostic to a plain dict (keeps it JSON-clean)."""
    try:
        return {
            "line": d.range.start.line if d.range else None,
            "character": d.range.start.character if d.range else None,
            "severity": int(d.severity) if d.severity else None,
            "source": d.source,
            "message": d.message,
        }
    except Exception:
        return {"message": str(d)}


def snapshot(ls, uri, diagnostics=None, contents=None):
    """Write the current workspace state to the snapshot file.

    Called by the LSP after publishing diagnostics.  Captures:
      - every open document's URI + current contents (from the workspace,
        so unsaved edits are included)
      - the diagnostics just published for the given doc
    Failures are silent — snapshotting must never break the LSP."""
    try:
        state = _read_or_new()
        # refresh the doc's contents from the workspace (live, unsaved edits)
        docs = {}
        try:
            for doc_uri, doc in ls.workspace.text_documents.items():
                docs[doc_uri] = {"contents": "\n".join(doc.lines) if doc.lines else ""}
        except Exception:
            pass
        state["documents"] = docs
        if diagnostics is not None:
            state["diagnostics"][uri] = [_diag_to_dict(d) for d in diagnostics]
        state["updated"] = time.time()
        state["updated_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        tmp = SNAPSHOT_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, SNAPSHOT_PATH)
    except Exception:
        pass


def _read_or_new():
    """Load the previous snapshot if present, else a fresh structure."""
    try:
        with open(SNAPSHOT_PATH) as f:
            return json.load(f)
    except Exception:
        return {"documents": {}, "diagnostics": {}, "updated": 0.0}
