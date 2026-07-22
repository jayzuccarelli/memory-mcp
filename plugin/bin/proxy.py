#!/usr/bin/env python3
"""stdio-to-HTTP bridge for the memory server.

Claude Code can only expand real environment variables inside a plugin's
.mcp.json, which would force the server URL and token into the user's shell
profile. Registering a stdio command instead lets the config live in one file
that this process reads itself, so installing the plugin needs no shell edits
and no JSON edits.

Reads JSON-RPC messages from stdin, forwards them to the HTTP server, writes
replies to stdout. Stdlib only — it runs wherever the plugin is installed.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from config import PROTOCOL_VERSION, load_config  # noqa: E402

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class Bridge:
    def __init__(self, url: str, token: str, timeout: float) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id: str | None = None

    def post(self, payload: dict) -> dict | None:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id

        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self.session_id = sid
            body = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("response too large")

        raw = body.decode("utf-8", "replace")
        if not raw.strip():
            return None
        # SSE frames arrive as repeated "data: {...}" lines; take the last.
        if any(ln.startswith("data:") for ln in raw.splitlines()):
            chunks = [
                ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")
            ]
            if not chunks:
                return None
            raw = chunks[-1]
        return json.loads(raw)


def _error(req_id: object, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32000, "message": message},
    }


def main() -> int:
    cfg = load_config()
    if not cfg.url:
        # Not configured yet. Answer initialize so the client shows the server
        # as connected-but-empty rather than crash-looping, and say why.
        bridge = None
    else:
        bridge = Bridge(cfg.url, cfg.token, cfg.timeout)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue

        req_id = msg.get("id")
        is_notification = req_id is None

        if bridge is None:
            if is_notification:
                continue
            if msg.get("method") == "initialize":
                reply = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": "memory (not configured)",
                            "version": "0",
                        },
                    },
                }
            else:
                reply = _error(
                    req_id, "memory-mcp is not configured. Run /memory:setup"
                )
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
            continue

        try:
            reply = bridge.post(msg)
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
            if is_notification:
                continue
            reply = _error(req_id, f"memory server unreachable: {e}")

        if reply is None:
            continue
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
