#!/usr/bin/env python3
"""livecheck_mcp.py — expose the LSP's live editor state to the AI.

The AI (opencode) can't reach into Helix — no editor control socket.  But the
cmsis-svd LSP holds the live truth: every open document's current contents
(including unsaved edits) and the diagnostics it publishes to the gutter.
lsp_state.py writes that to /tmp/livecheck-lsp-state.json; this server reads
it and exposes it as MCP tools, so the AI sees exactly what the editor and
the chip are doing without fighting Helix.

Port 8794.  Read-only: never touches the Forth socket, never modifies the
editor or the project — it only READS the LSP snapshot + the chip's cmd
socket + the summary files.

Usage:
  <venv>/python livecheck_mcp.py --port 8794
"""
import argparse
import json
import os
import socket
import time

from mcp.server.fastmcp import FastMCP

import lsp_state

SERVER_ID = "livecheck-mcp:8795"


def _tag(obj):
    return dict(obj, server=SERVER_ID)


# --------------------------------------------------------------------------
# Chip state (read-only, via the swdd cmd socket — same path Regmon uses)
# --------------------------------------------------------------------------
CMD_SOCK = "/tmp/swdd-cmd.sock"
SUMMARY_DIR = os.path.expanduser("~/fossil")


def _cmd(command, timeout=4):
    """Send a command to the swdd cmd socket; return the reply or ''."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(CMD_SOCK)
        s.sendall((command + "\n").encode())
        time.sleep(0.2)
        out = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                out += chunk
        except socket.timeout:
            pass
        s.close()
        return out.decode(errors="replace").strip()
    except Exception:
        return ""


def _chip_alive():
    """True if the swdd daemon is up and answers the ping."""
    return "pong" in _cmd("ping", timeout=2)


def _read_file(path, limit=0):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = f.read()
        if limit and len(data) > limit:
            return data[:limit] + "\n...[truncated]"
        return data
    except Exception:
        return ""


def build_mcp(host="127.0.0.1", port=8794):
    mcp = FastMCP(
        "livecheck-mcp",
        host=host,
        port=port,
        instructions=(
            "Live view of the cmsis-svd LSP's workspace + the bench chip.  "
            "Reads the LSP state snapshot (open documents, unsaved contents, "
            "gutter diagnostics) and the swdd chip socket.  Use this to see "
            "what the editor and the silicon are doing RIGHT NOW — never "
            "touches the Forth socket or modifies anything.\n\n"
            "CONTEXT BUDGET (IMPORTANT): files can be large and your context "
            "window is limited.  ALWAYS pass start/end (1-based line numbers) "
            "or limit=N to document_contents — never fetch a whole file "
            "unless you know it is small.  Use active_documents first to see "
            "what is open, then slice just the region you need.  Use "
            "document_diagnostics WITHOUT a uri for per-file counts only; "
            "add a uri + line range only for detail on one file."
        ),
    )
    mcp.settings.stateless_http = True

    @mcp.tool()
    def active_documents() -> str:
        """List the currently open documents in the editor (URIs + whether
        each has diagnostics).  The AI's 'what am I working on' view."""
        state = lsp_state._read_or_new()
        docs = state.get("documents", {})
        diags = state.get("diagnostics", {})
        return json.dumps(_tag({
            "updated_iso": state.get("updated_iso"),
            "documents": [
                {"uri": uri,
                 "chars": len(info.get("contents", "")),
                 "diagnostics": len(diags.get(uri, []))}
                for uri, info in docs.items()
            ],
        }), indent=2)

    @mcp.tool()
    def document_contents(uri: str = "", start: int = 1, end: int = 0, limit: int = 0) -> str:
        """Return the CURRENT contents of an open document (including unsaved
        edits).  With no uri, returns the first/only open document.

        SLICING (essential — whole files blow small contexts): give start/end
        as 1-based line numbers to get just that range (end=0 means 'to the
        end').  Or give limit=N to cap at N lines from the top.  The response
        reports which lines it returned, so you can page through a big file
        without loading it all at once."""
        state = lsp_state._read_or_new()
        docs = state.get("documents", {})
        if not uri:
            uri = next(iter(docs), "")
        info = docs.get(uri)
        if info is None:
            return json.dumps(_tag({"error": "no such open doc", "uri": uri}), indent=2)
        lines = info.get("contents", "").split("\n")
        total = len(lines)
        if limit:
            end = min(limit, total)
            start = 1
        if start < 1:
            start = 1
        if end <= 0 or end > total:
            end = total
        if end < start:
            end = start
        slice_lines = lines[start - 1:end]
        return json.dumps(_tag({
            "uri": uri,
            "total_lines": total,
            "returned_lines": f"{start}-{end}",
            "contents": "\n".join(slice_lines),
        }), indent=2)

    @mcp.tool()
    def document_diagnostics(uri: str = "", start: int = 1, end: int = 0) -> str:
        """Return the gutter diagnostics (orange/blue marks) for an open
        document.  With no uri, returns diagnostics for ALL open docs but
        ONLY the counts per file (keeps the response small).  Give a uri +
        optional 1-based line range to get the full diagnostic detail for
        just that slice."""
        state = lsp_state._read_or_new()
        diags = state.get("diagnostics", {})
        if uri:
            items = diags.get(uri, [])
            if start > 1 or end:
                items = [d for d in items
                         if (d.get("line") or 0) + 1 >= start
                         and (end <= 0 or (d.get("line") or 0) + 1 <= end)]
            return json.dumps(_tag({uri: items}), indent=2)
        # no uri: just the counts per file, so it never blows context
        counts = {u: len(d) for u, d in diags.items()}
        return json.dumps(_tag(counts), indent=2)

    @mcp.tool()
    def chip_state() -> str:
        """Is the bench chip reachable?  Reads the swdd daemon (ping + info)."""
        alive = _chip_alive()
        info = {"alive": alive}
        if alive:
            info["info"] = _cmd("info", timeout=3)
        return json.dumps(_tag(info), indent=2)

    @mcp.tool()
    def project_summary(project_dir: str = "") -> str:
        """Read the F4-generated project summary.md (the live-chip snapshot:
        memory, enables, config, dependency graph).  Pass the project dir or
        let it guess from the open document."""
        state = lsp_state._read_or_new()
        if not project_dir:
            uri = next(iter(state.get("documents", {})), "")
            if uri.startswith("file://"):
                project_dir = os.path.dirname(uri[len("file://"):])
        if not project_dir:
            return json.dumps(_tag({"error": "no project dir — pass one"}), indent=2)
        summary = _read_file(os.path.join(project_dir, "summary.md"))
        if not summary:
            summary = _read_file(os.path.join(project_dir, "summary-fossil.md"))
        return json.dumps(_tag({"project": project_dir,
                                "summary": summary or "(none yet — press F4)"}), indent=2)

    @mcp.tool()
    def snapshot_age() -> str:
        """How fresh is the LSP snapshot?  A stale snapshot means the editor
        hasn't published recently (idle, or the LSP restarted)."""
        state = lsp_state._read_or_new()
        age = time.time() - state.get("updated", 0)
        return json.dumps(_tag({
            "updated_iso": state.get("updated_iso"),
            "age_seconds": round(age, 1),
            "fresh": age < 30,
        }), indent=2)

    return mcp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8794)
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
