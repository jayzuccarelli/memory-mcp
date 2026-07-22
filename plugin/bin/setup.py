#!/usr/bin/env python3
"""Write the plugin's config from a single connection string.

Usage: setup.py <connection-string>

The server prints the connection string on startup. It is one opaque blob so a
user has one thing to copy, not two fields to keep straight:

    memory://<token>@<host>[:<port>][/<path>]

Falls back to accepting a plain URL plus token as two arguments, for anyone who
would rather paste them separately.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from config import load_config, save_config  # noqa: E402


def parse_connection_string(s: str) -> tuple[str, str]:
    """memory://<token>@host/path -> (https url, token)."""
    if not s.startswith("memory://"):
        raise ValueError("connection string must start with memory://")
    rest = s[len("memory://") :]
    if "@" not in rest:
        raise ValueError("connection string is missing the token")
    token_part, _, hostpart = rest.partition("@")
    token = token_part
    # Tokens are emitted base64url-encoded so a '@' or '/' inside one can't
    # split the string in the wrong place.
    try:
        pad = "=" * (-len(token_part) % 4)
        decoded = base64.urlsafe_b64decode(token_part + pad).decode()
        if decoded:
            token = decoded
    except Exception:
        pass
    if not hostpart:
        raise ValueError("connection string is missing the host")
    split = urlsplit("//" + hostpart, scheme="https")
    path = split.path or "/mcp"
    url = urlunsplit(("https", split.netloc, path, "", ""))
    return url, token


def main(argv: list[str]) -> int:
    if not argv:
        cfg = load_config()
        if cfg.url:
            print(f"memory-mcp is configured: {cfg.url}")
            return 0
        print("Not configured. Run: /memory:setup <connection-string>")
        return 1

    try:
        if len(argv) >= 2 and argv[0].startswith(("http://", "https://")):
            url, token = argv[0], argv[1]
        else:
            url, token = parse_connection_string(argv[0].strip())
    except ValueError as e:
        print(f"Could not read that connection string: {e}")
        return 1

    path = save_config(url, token)
    print(f"Saved to {path} (owner-only).")
    print(f"Server: {url}")
    print("Run /reload-plugins, then start a new session.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
