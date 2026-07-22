"""Personal memory MCP server.

Markdown files in MEMORY_DIR are the source of truth.
Exposes list/read/search/write/delete tools over streamable-http.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MEMORY_DIR = Path(os.environ.get("MEMORY_DIR", "memory")).resolve()
MEMORY_TOKEN = os.environ.get("MEMORY_TOKEN")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "3333"))
# When True, accept any Host header. Required when fronting with a reverse
# proxy (e.g. Tailscale Funnel) that forwards the public hostname. Bearer
# auth + HTTPS still gate access; DNS rebinding doesn't add meaningful
# defense in this threat model.
TRUST_PROXY = os.environ.get("TRUST_PROXY", "false").lower() in ("1", "true", "yes")
# When True, memories marked `scope: private` are served like any other. Leave
# it off on a publicly reachable server — that flag is the only thing keeping
# them off the wire.
SERVE_PRIVATE = os.environ.get("SERVE_PRIVATE", "false").lower() in (
    "1",
    "true",
    "yes",
)

# Monkey-patch BEFORE importing mcp-use so the session manager picks up the
# disabled host check from the start. mcp-use/FastMCP auto-enable DNS-rebinding
# protection when bound to localhost, which rejects proxied requests.
if TRUST_PROXY:
    from mcp.server import transport_security as _ts

    async def _no_host_check(self, request, is_post=False):
        if is_post:
            ct = request.headers.get("content-type", "")
            if not ct.lower().startswith("application/json"):
                from starlette.responses import Response

                return Response("Invalid Content-Type header", status_code=400)
        return None

    _ts.TransportSecurityMiddleware.validate_request = _no_host_check

from mcp_use.server import MCPServer  # noqa: E402
from mcp_use.server.auth import AccessToken, BearerAuthProvider  # noqa: E402

if not MEMORY_DIR.is_dir():
    raise SystemExit(f"MEMORY_DIR does not exist: {MEMORY_DIR}")


class TokenAuth(BearerAuthProvider):
    async def verify_token(self, token: str) -> AccessToken | None:
        if MEMORY_TOKEN and token == MEMORY_TOKEN:
            return AccessToken(token=token, claims={"sub": "owner"})
        return None


def _candidates(path_or_id: str) -> list[str]:
    """Filename spellings to try for a given id.

    Claude Code hyphenates the frontmatter id but underscores the filename
    (`name: a-b-c` in `a_b_c.md`), so accept either separator.
    """
    name = path_or_id.strip()
    if not name.endswith(".md"):
        name = f"{name}.md"
    stem = name[:-3]
    out = [name]
    for alt in (stem.replace("-", "_"), stem.replace("_", "-")):
        if alt != stem:
            out.append(f"{alt}.md")
    return out


def _resolve(path_or_id: str) -> Path:
    """Resolve a user-provided path or id to a markdown file inside MEMORY_DIR.

    Accepts 'identity', 'identity.md', or 'projects/foo.md'. Rejects traversal.
    Returns the first spelling that exists, else the canonical one so callers
    still get a sensible path to report or write to.
    """
    resolved: Path | None = None
    for cand in _candidates(path_or_id):
        target = (MEMORY_DIR / cand).resolve()
        if not str(target).startswith(str(MEMORY_DIR) + os.sep):
            raise ValueError(f"path escapes memory dir: {path_or_id}")
        if resolved is None:
            resolved = target
        if target.is_file():
            return target
    return resolved


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter into a flat dict of strings.

    One level of nesting is flattened into the same dict, because Claude Code
    writes its own memories with `type` under a `metadata:` block rather than at
    the top level. Top-level keys win over nested ones.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    nested: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        target = nested if k[:1] in " \t" else meta
        target[k.strip()] = v.strip().strip("\"'")
    for k, v in nested.items():
        meta.setdefault(k, v)
    return meta, body


def _memory_id(meta: dict[str, str], path: Path) -> str:
    """Claude Code calls it `name`; this server calls it `id`. Accept both."""
    return meta.get("id") or meta.get("name") or path.stem


def _is_private(meta: dict[str, str]) -> bool:
    """`scope: private` memories are never served unless SERVE_PRIVATE is set.

    This is the deny-list: everything is readable by default, and you opt a
    memory out by marking it private. Opt-in would leave the store empty.
    """
    return not SERVE_PRIVATE and meta.get("scope", "").lower() == "private"


def _iter_memory_files() -> list[Path]:
    return sorted(p for p in MEMORY_DIR.rglob("*.md") if p.name != "MEMORY.md")


server = MCPServer(
    name="memory",
    version="0.1.0",
    instructions=(
        "Personal cross-LLM memory. The file MEMORY.md is the index — read it "
        "first to discover what's available. Use search_memories for fuzzy "
        "lookups, read_memory to load a specific file in full. When you learn "
        "something durable about the user, write it with write_memory using "
        "the schema shown in any existing memory file."
    ),
    auth=TokenAuth() if MEMORY_TOKEN else None,
    host=HOST,
    port=PORT,
)

if TRUST_PROXY:
    # MCPServer.__init__ already built `self.app` and the session manager with
    # FastMCP's auto-locked-down security settings. We override the settings
    # AND rebuild both — the same pattern mcp-use uses internally when host
    # changes at runtime (see _apply_dns_rebinding_protection / run()).
    server.settings.transport_security = _ts.TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )
    server._session_manager = None
    server.app = server.streamable_http_app()


@server.tool(
    name="list_memories",
    description=(
        "List all memories with their frontmatter metadata. Optionally filter "
        "by type (identity|project|preference|reference|fact|user|feedback) or "
        "scope. Archived memories are excluded unless include_archived=True."
    ),
)
async def list_memories(
    type: str | None = None,
    scope: str | None = None,
    include_archived: bool = False,
) -> list[dict]:
    out: list[dict] = []
    for path in _iter_memory_files():
        meta, _ = _parse_frontmatter(path.read_text(encoding="utf-8"))
        if _is_private(meta):
            continue
        if not include_archived and meta.get("archived", "").lower() == "true":
            continue
        if type and meta.get("type") != type:
            continue
        if scope and meta.get("scope") != scope:
            continue
        out.append(
            {
                "path": str(path.relative_to(MEMORY_DIR)),
                "id": _memory_id(meta, path),
                "type": meta.get("type", ""),
                "scope": meta.get("scope", ""),
                "description": meta.get("description", ""),
                "tags": meta.get("tags", ""),
                "updated": meta.get("updated", ""),
            }
        )
    return out


@server.tool(
    name="read_memory",
    description=(
        "Read the full content of a memory file by id or path "
        "(e.g. 'identity' or 'identity.md'). Returns the raw markdown."
    ),
)
async def read_memory(id_or_path: str) -> str:
    target = _resolve(id_or_path)
    if not target.is_file():
        raise FileNotFoundError(f"no such memory: {id_or_path}")
    text = target.read_text(encoding="utf-8")
    meta, _ = _parse_frontmatter(text)
    if _is_private(meta):
        # Same error as a missing file — don't confirm a private memory exists.
        raise FileNotFoundError(f"no such memory: {id_or_path}")
    return text


@server.tool(
    name="search_memories",
    description=(
        "Case-insensitive substring search across memory files. Returns "
        "matching memories with the line(s) that matched. Optionally filter "
        "by type or scope."
    ),
)
async def search_memories(
    query: str,
    type: str | None = None,
    scope: str | None = None,
    max_results: int = 20,
) -> list[dict]:
    needle = query.lower()
    hits: list[dict] = []
    for path in _iter_memory_files():
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        if _is_private(meta):
            continue
        if type and meta.get("type") != type:
            continue
        if scope and meta.get("scope") != scope:
            continue
        matches = [line.strip() for line in body.splitlines() if needle in line.lower()]
        if needle in meta.get("description", "").lower() and not matches:
            matches = [meta.get("description", "")]
        if matches:
            hits.append(
                {
                    "path": str(path.relative_to(MEMORY_DIR)),
                    "id": _memory_id(meta, path),
                    "description": meta.get("description", ""),
                    "matches": matches[:5],
                }
            )
        if len(hits) >= max_results:
            break
    return hits


@server.tool(
    name="write_memory",
    description=(
        "Create or overwrite a memory file. 'path' is relative to the memory "
        "directory (e.g. 'preferences-tooling.md'). 'content' must include "
        "YAML frontmatter with fields: id, type, scope, description, "
        "created, updated, tags. Refuse to write outside the memory directory."
    ),
)
async def write_memory(path: str, content: str) -> dict:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.is_file()
    if existed and _is_private(_parse_frontmatter(target.read_text("utf-8"))[0]):
        raise FileNotFoundError(f"no such memory: {path}")
    if not re.match(r"^---\s*\n", content):
        raise ValueError("content must begin with YAML frontmatter (---)")
    target.write_text(content, encoding="utf-8")
    return {
        "path": str(target.relative_to(MEMORY_DIR)),
        "action": "updated" if existed else "created",
        "bytes": len(content),
        "today": date.today().isoformat(),
    }


@server.tool(
    name="delete_memory",
    description=(
        "Delete a memory file by id or path. Use sparingly — prefer setting "
        "'archived: true' in frontmatter via write_memory to preserve history."
    ),
)
async def delete_memory(id_or_path: str) -> dict:
    target = _resolve(id_or_path)
    if not target.is_file():
        raise FileNotFoundError(f"no such memory: {id_or_path}")
    if _is_private(_parse_frontmatter(target.read_text("utf-8"))[0]):
        raise FileNotFoundError(f"no such memory: {id_or_path}")
    target.unlink()
    return {"path": str(target.relative_to(MEMORY_DIR)), "action": "deleted"}


if __name__ == "__main__":
    if not MEMORY_TOKEN:
        print("WARNING: MEMORY_TOKEN unset — server will accept unauthenticated calls.")
        print("Set MEMORY_TOKEN in .env before exposing via Tailscale Funnel.")
    print(f"memory dir: {MEMORY_DIR}")
    print(f"listening:  http://{HOST}:{PORT}")
    print(f"inspector:  http://{HOST}:{PORT}/")
    server.run(transport="streamable-http")
