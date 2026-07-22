"""Shared config for the plugin's hook and stdio proxy.

One file, one format, written by /memory:setup and read by both halves. Nothing
lives in the shell profile or in settings.json, because asking a user to hand-
edit either of those is not an install.

Resolution order, first hit wins:
  1. MEMORY_MCP_URL / MEMORY_MCP_TOKEN in the environment (power users, CI)
  2. ~/.config/memory-mcp/config.json   (what /memory:setup writes)
  3. ~/.memory-mcp.env                  (older shell-style file, still honored)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"

CONFIG_JSON = Path(
    os.environ.get("MEMORY_MCP_CONFIG", "~/.config/memory-mcp/config.json")
).expanduser()
LEGACY_ENV = Path(
    os.environ.get("MEMORY_MCP_ENV_FILE", "~/.memory-mcp.env")
).expanduser()


@dataclass
class Config:
    url: str = ""
    token: str = ""
    timeout: float = 5.0


def _from_json() -> dict[str, str]:
    if not CONFIG_JSON.is_file():
        return {}
    try:
        data = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _from_legacy_env() -> dict[str, str]:
    """Parse `KEY=value` / `export KEY="value"` lines."""
    if not LEGACY_ENV.is_file():
        return {}
    out: dict[str, str] = {}
    for line in LEGACY_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip("'\"")
    return out


def load_config() -> Config:
    """Never raises. A broken config yields an empty one, so callers fail open."""
    try:
        j, e = _from_json(), _from_legacy_env()
    except OSError:
        j, e = {}, {}

    def pick(env_key: str, json_key: str) -> str:
        if os.environ.get(env_key):
            return os.environ[env_key]
        if j.get(json_key):
            return str(j[json_key])
        return e.get(env_key, "")

    timeout_raw = pick("MEMORY_MCP_TIMEOUT", "timeout") or "5"
    try:
        timeout = float(timeout_raw)
    except ValueError:
        timeout = 5.0

    return Config(
        url=pick("MEMORY_MCP_URL", "url"),
        token=pick("MEMORY_MCP_TOKEN", "token"),
        timeout=timeout,
    )


def save_config(url: str, token: str) -> Path:
    """Write the config with owner-only permissions. Returns the path."""
    CONFIG_JSON.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_JSON.write_text(
        json.dumps({"url": url, "token": token}, indent=2) + "\n", encoding="utf-8"
    )
    CONFIG_JSON.chmod(0o600)
    return CONFIG_JSON
