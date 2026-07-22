#!/usr/bin/env python3
"""Keep local memory writes and the memory server in sync.

Claude Code has its own file-based memory. Without this, "remember X" lands in
whichever store the model happens to reach for, and the two drift apart — which
defeats the point of a memory layer that is supposed to follow you between
machines.

Modes (config key "write_mode"):
    mirror    default. Runs on PostToolUse: after a local memory file is
              written, push a copy to the server. Both stores stay usable.
    redirect  Runs on PreToolUse: deny the local write and tell the model to
              call write_memory instead. One store, strictly.
    off       Do nothing.

Always fails open. A memory server that is down must never block a write.
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from client import Client  # noqa: E402
from config import load_config  # noqa: E402

REDIRECT_MESSAGE = (
    "Local memory files are disabled: this project keeps memories on the memory "
    "MCP server so they are available from every machine. Call the memory "
    "server's write_memory tool with the same content instead."
)


def is_memory_file(path: str) -> bool:
    """Claude Code keeps its memories in a 'memory' directory as markdown."""
    if not path.endswith(".md"):
        return False
    parts = Path(path).parts
    return "memory" in parts and Path(path).name != "MEMORY.md"


def emit(payload: dict) -> None:
    print(json.dumps(payload))


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0

    cfg = load_config()
    if cfg.write_mode == "off" or not cfg.url:
        return 0

    path = str((data.get("tool_input") or {}).get("file_path", ""))
    if not is_memory_file(path):
        return 0

    event = data.get("hook_event_name", "")

    if cfg.write_mode == "redirect":
        if event != "PreToolUse":
            return 0
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": REDIRECT_MESSAGE,
                }
            }
        )
        return 0

    # mirror: the local write already happened, copy it up.
    if event != "PostToolUse":
        return 0
    try:
        content = Path(path).read_text(encoding="utf-8")
    except OSError:
        return 0
    if not content.startswith("---"):
        # The server requires frontmatter. Not a memory we can mirror.
        return 0

    try:
        client = Client(cfg, "memory-mirror-hook")
        client.handshake()
        client.call("write_memory", {"path": Path(path).name, "content": content})
    except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
        emit({"systemMessage": f"memory-mcp: could not mirror {Path(path).name} ({e})"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
