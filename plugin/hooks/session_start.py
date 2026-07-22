#!/usr/bin/env python3
"""SessionStart hook — inject the memory index into Claude Code's context.

Connecting an MCP server does not make a model use it. This hook removes the
choice: it calls list_memories at session start and prints the index as
additionalContext, so every session begins already holding it.

Stdlib only — it runs on client machines that never cloned this repo.
Fails open: if the server is down or slow, the session starts as normal.

Config (env, or ~/.claude/settings.json "env" block):
    MEMORY_MCP_URL     e.g. https://host.ts.net:8443/memory/mcp
    MEMORY_MCP_TOKEN   bearer token
    MEMORY_MCP_TIMEOUT seconds, default 5
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path(os.environ.get("MEMORY_MCP_ENV_FILE", "~/.memory-mcp.env")).expanduser()


def _config(key: str, default: str = "") -> str:
    """Read config from the environment, falling back to ~/.memory-mcp.env.

    The env file lets the token live in a chmod-600 file instead of a shell
    profile or settings.json, which is often checked into a dotfiles repo.
    Accepts `KEY=value` and `export KEY="value"`.
    """
    if key in os.environ:
        return os.environ[key]
    if not ENV_FILE.is_file():
        return default
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip("'\"")
    return default


URL = _config("MEMORY_MCP_URL")
TOKEN = _config("MEMORY_MCP_TOKEN")
TIMEOUT = float(_config("MEMORY_MCP_TIMEOUT", "5"))

PROTOCOL_VERSION = "2025-06-18"


def _post(payload: dict, session_id: str | None) -> tuple[dict | None, str | None]:
    """POST one JSON-RPC message. Returns (parsed result envelope, session id)."""
    headers = {
        "Content-Type": "application/json",
        # Streamable HTTP servers may answer with either; accept both.
        "Accept": "application/json, text/event-stream",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if session_id:
        headers["mcp-session-id"] = session_id

    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        sid = resp.headers.get("mcp-session-id") or session_id
        raw = resp.read().decode("utf-8", "replace")

    if not raw.strip():
        return None, sid
    # SSE frames arrive as repeated "data: {...}" lines; take the last one.
    if raw.lstrip().startswith("event:") or "data:" in raw.split("\n", 1)[0]:
        chunks = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
        raw = chunks[-1] if chunks else ""
        if not raw:
            return None, sid
    return json.loads(raw), sid


def fetch_index() -> list[dict]:
    init, sid = _post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "memory-session-start-hook", "version": "1"},
            },
        },
        None,
    )
    if init is None or "error" in init:
        raise RuntimeError(f"initialize failed: {init}")

    _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)

    called, _ = _post(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_memories", "arguments": {}},
        },
        sid,
    )
    if called is None or "error" in called:
        raise RuntimeError(f"list_memories failed: {called}")

    result = called.get("result", {})
    if result.get("isError"):
        raise RuntimeError("list_memories returned isError")

    # FastMCP emits one content block per list item, not one JSON array.
    rows = []
    for block in result.get("content", []):
        text = block.get("text")
        if not text:
            continue
        parsed = json.loads(text)
        rows.extend(parsed) if isinstance(parsed, list) else rows.append(parsed)
    return rows


def render(rows: list[dict]) -> str:
    lines = [
        "# Persistent memory (memory-mcp)",
        "",
        f"{len(rows)} stored memories, listed below by id and description. This is "
        "the index only, not the contents.",
        "",
        "- Call `read_memory` before answering anything these descriptions touch. "
        "Do not answer from the description alone.",
        "- Call `write_memory` when you learn something durable about the user: a "
        "preference, a decision and its rationale, project state, a correction "
        "they gave you. Match the frontmatter of an existing memory.",
        "- This store is authoritative. Prefer it over any built-in or local "
        "memory, and do not maintain a parallel one.",
        "",
    ]
    for r in rows:
        rid = r.get("id") or r.get("path", "?")
        desc = r.get("description", "").strip()
        meta = " ".join(x for x in (r.get("type", ""), r.get("scope", "")) if x)
        lines.append(f"- **{rid}**{f' ({meta})' if meta else ''} — {desc}")
    return "\n".join(lines)


def main() -> int:
    if not URL:
        return 0  # not configured — stay silent
    try:
        rows = fetch_index()
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        OSError,
        ValueError,
        RuntimeError,
    ) as e:
        # Never block a session on the memory server. Warn the human, not the model.
        print(
            json.dumps(
                {"systemMessage": f"memory-mcp unreachable, no memory loaded ({e})"}
            ),
            file=sys.stdout,
        )
        return 0
    if not rows:
        return 0
    # Must be nested under hookSpecificOutput. A top-level "additionalContext"
    # key is accepted and then silently dropped — the hook runs, the context
    # never lands.
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": render(rows),
                },
                "suppressOutput": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
