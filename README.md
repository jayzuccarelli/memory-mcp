# memory-mcp

A personal cross-LLM memory layer. Markdown files are the source of truth.
The server exposes them as MCP tools so Claude, ChatGPT, Cursor, Mistral, etc.
can read, search, and update memories, with no cold start in any new chat.

## Layout

```
memory/
  MEMORY.md            # always-loaded index, one line per memory
  identity.md          # who you are
  project-*.md         # one per active project
  preferences-*.md     # one per preference cluster
  reference-*.md       # external resources / how-tos
server.py              # mcp-use server (HTTP)
pyproject.toml         # uv-managed deps
.env.example           # MEMORY_TOKEN, HOST, PORT, MEMORY_DIR
```

Each memory file has YAML frontmatter:

```yaml
---
id: identity
type: identity            # identity | project | preference | reference | fact
scope: global             # global | project:<name> | session
description: Who I am, role, focus
created: 2026-05-06
updated: 2026-05-06
tags: [profile]
# archived: true         # set to hide from default search
---
```

## Quickstart

```bash
# 1. Install uv if you don't have it (it brings its own Python).
#    See https://docs.astral.sh/uv for other install methods.
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install deps.
uv sync

# 3. Seed your memory directory from the templates.
#    memory/ is gitignored, so your real memories never leave the host.
cp -r memory.example memory

# 4. Create your .env from the example.
cp .env.example .env

# 5. Generate a bearer token.
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
#    Copy the output and paste it into .env as:
#        MEMORY_TOKEN=<paste>

# 6. Start the server.
uv run python server.py
#    Listens on http://127.0.0.1:3333/mcp
```

The server speaks MCP over streamable HTTP at `/mcp` and does not serve a
browser UI. To poke at the tools by hand, point the
[MCP Inspector](https://github.com/modelcontextprotocol/inspector) at
`http://127.0.0.1:3333/mcp` with your bearer token.

## Tools

- `list_memories(type?, scope?, include_archived?)`
- `read_memory(id_or_path)`
- `search_memories(query, type?, scope?, max_results?)`
- `write_memory(path, content)`, where content must start with `---` frontmatter
- `delete_memory(id_or_path)`

## Connect a client

Pick the URL that matches where the client runs relative to the server:

| Setup | URL |
|---|---|
| Client on the same machine as the server | `http://127.0.0.1:3333/mcp` |
| Client on your LAN or tailnet | `http://<host>:3333/mcp` |
| ChatGPT.com / Claude.ai web / Mistral Le Chat | public HTTPS URL (see [Public exposure](#public-exposure)) |

The `<TOKEN>` below is the `MEMORY_TOKEN` you generated in step 5.

### Claude Code

```bash
claude mcp add --transport http -s user memory <URL> \
  -H "Authorization: Bearer <TOKEN>"
claude mcp list        # expect: "memory · Connected"
```

### Claude Desktop, Cursor, Windsurf, Cline

Add to the client's MCP config (path varies per client):

```json
{
  "mcpServers": {
    "memory": {
      "type": "http",
      "url": "<URL>",
      "headers": { "Authorization": "Bearer <TOKEN>" }
    }
  }
}
```

### ChatGPT / Claude.ai web

- **ChatGPT** (Pro/Team/Enterprise → Settings → Connectors → Add)
- **Claude.ai** (Pro+ → Settings → Connectors → Add)

Both need a **public HTTPS URL**, see below. Paste the URL, choose bearer
auth, paste `<TOKEN>`.

## Public exposure

Only needed for ChatGPT.com, Claude.ai web, and Mistral Le Chat, which hit
the server from the provider's backend, not your network. Skip this section
if you're only using Claude Code / Desktop / Cursor.

Any HTTPS reverse-proxy works. The simplest option is
[Tailscale Funnel](https://tailscale.com/kb/1223/funnel):

```bash
sudo tailscale funnel --bg 3333
```

That prints a public URL like `https://<host>.<tailnet>.ts.net`. Append
`/mcp` and use it as `<URL>` in the client config. When the server sits
behind a proxy that forwards a different Host header, set `TRUST_PROXY=true`
in `.env` so FastMCP doesn't reject the request.

Cloudflare Tunnel, ngrok, or your own domain + nginx + Let's Encrypt work
equally.

## Security

- The bearer token is the only thing between the public Funnel URL and your
  memories. Treat it like a password.
- Don't commit `.env`. The `.gitignore` excludes it.
- Rotate the token by generating a new one and updating each connector.

## Development

```bash
make check   # ruff lint + format + tool-registry smoke
make run     # uv run python server.py
```

## Known limits

- No embeddings: search is substring-based. Fine for personal-scale; add a
  sidecar SQLite + embeddings later if needed.
- No write review queue: the LLM can write directly. Watch the index.
- No multi-user. This is a single-tenant server.
