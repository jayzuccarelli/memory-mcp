# memory-mcp

A personal cross-LLM memory layer. Markdown files are the source of truth.
The server exposes them as MCP tools so Claude, ChatGPT, Cursor, Mistral, etc.
can read, search, and update memories — no cold start in any new chat.

## Layout

```
memory/
  MEMORY.md            # always-loaded index, one line per memory
  identity.md          # who you are
  project-*.md         # one per active project
  preferences-*.md     # one per preference cluster
  ref-*.md             # external resources / how-tos
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

## Run locally

```bash
# 1. Seed the memory directory from the templates
cp -r memory.example memory

# 2. Generate a bearer token and drop it in .env
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"  # paste into MEMORY_TOKEN

# 3. Start the server
uv run python server.py
```

`memory/` is gitignored — your real memories never leave the host.
`memory.example/` is the template set; edit copies in `memory/` instead.

The Inspector is at `http://127.0.0.1:3333/` while the server is running —
use it to call tools manually before hooking up an LLM.

## Tools

- `list_memories(type?, scope?, include_archived?)`
- `read_memory(id_or_path)`
- `search_memories(query, type?, scope?, max_results?)`
- `write_memory(path, content)` — content must start with `---` frontmatter
- `delete_memory(id_or_path)`

## Connecting clients

### Claude Code (CLI, any machine)

One line, using the CLI installed by Claude Code:

```bash
claude mcp add --transport http -s user memory <URL> \
  -H "Authorization: Bearer <TOKEN>"
```

- `<URL>` is `http://127.0.0.1:3333/mcp` on the host, or your public/tailnet
  URL from anywhere else (see "Exposing publicly with Tailscale Funnel"
  below — e.g. `https://<host>.<tailnet>.ts.net:8443/memory/mcp`).
- `<TOKEN>` is the `MEMORY_TOKEN` you generated into `.env`.
- `-s user` makes it available in every project on that machine.

Verify:

```bash
claude mcp list       # should show "memory · Connected"
```

Or launch a session and type `/mcp`, or ask the model to `call list_memories`.

### Claude Desktop, Cursor, Windsurf, Cline

Same shape — most clients accept an `mcpServers` block with `url` and
`headers`. Config file path varies per client; check its docs.

```json
{
  "mcpServers": {
    "memory": {
      "type": "http",
      "url": "http://127.0.0.1:3333/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN_HERE" }
    }
  }
}
```

Swap `127.0.0.1` for the tailnet or Funnel host when connecting from another
machine.

## Exposing publicly with Tailscale Funnel

For ChatGPT.com, Claude.ai web, and Mistral Le Chat — these connect from the
provider's backend, not your tailnet. You need a public HTTPS URL.

On the host running `server.py` (e.g. the Vaio):

```bash
# 1. Have Tailscale installed and HTTPS enabled in the admin panel
sudo tailscale up
sudo tailscale set --advertise-routes=  # not needed, just check status

# 2. Bind the server to localhost (default in .env), then publish:
tailscale funnel --bg 3333

# 3. Note the public URL printed, e.g.:
#    https://memory.tail-scale-name.ts.net
```

Then in **ChatGPT** (Pro/Team/Enterprise → Settings → Connectors → Add):
- Server URL: `https://memory.tail-scale-name.ts.net/mcp`
- Auth: bearer token, paste `MEMORY_TOKEN`

Same in **Claude.ai** (Pro+ → Settings → Connectors).

## Security

- The bearer token is the only thing between the public Funnel URL and your
  memories. Treat it like a password.
- Don't commit `.env`. The `.gitignore` excludes it.
- Rotate the token by generating a new one and updating each connector.

## Known limits

- No embeddings — search is substring-based. Fine for personal-scale; add a
  sidecar SQLite + embeddings later if needed.
- No write review queue — the LLM can write directly. Watch the index.
- No multi-user. This is a single-tenant server.
