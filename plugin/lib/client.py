"""Minimal MCP client over streamable HTTP, shared by the plugin's hooks.

Stdlib only — hooks run on machines that never cloned this repo.
"""

from __future__ import annotations

import json
import urllib.request

from config import PROTOCOL_VERSION, Config

MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class Client:
    def __init__(self, cfg: Config, client_name: str) -> None:
        self.cfg = cfg
        self.client_name = client_name
        self.session_id: str | None = None

    def _post(self, payload: dict) -> dict | None:
        headers = {
            "Content-Type": "application/json",
            # Streamable HTTP servers may answer with either; accept both.
            "Accept": "application/json, text/event-stream",
        }
        if self.cfg.token:
            headers["Authorization"] = f"Bearer {self.cfg.token}"
        if self.session_id:
            headers["mcp-session-id"] = self.session_id

        req = urllib.request.Request(
            self.cfg.url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self.session_id = sid
            body = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("response too large")

        raw = body.decode("utf-8", "replace")
        if not raw.strip():
            return None
        # SSE frames arrive as repeated "data: {...}" lines; take the last one.
        # Check every line: a stream may open with a comment, `id:`, or `retry:`.
        if any(ln.startswith("data:") for ln in raw.splitlines()):
            chunks = [
                ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")
            ]
            if not chunks:
                return None
            raw = chunks[-1]
        return json.loads(raw)

    def handshake(self) -> None:
        init = self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": self.client_name, "version": "1"},
                },
            }
        )
        if init is None or "error" in init:
            raise RuntimeError(f"initialize failed: {init}")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, tool: str, arguments: dict) -> dict:
        out = self._post(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        )
        if out is None or "error" in out:
            raise RuntimeError(f"{tool} failed: {out}")
        result = out.get("result", {})
        if result.get("isError"):
            raise RuntimeError(f"{tool} returned isError")
        return result

    @staticmethod
    def rows(result: dict) -> list[dict]:
        """FastMCP emits one content block per list item, not one JSON array."""
        out: list[dict] = []
        for block in result.get("content", []):
            text = block.get("text")
            if not text:
                continue
            parsed = json.loads(text)
            out.extend(parsed) if isinstance(parsed, list) else out.append(parsed)
        return out
