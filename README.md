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
hooks/session_start.py # Claude Code SessionStart hook — injects the index
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
# 1. Install deps (uv installs Python + all packages; https://docs.astral.sh/uv)
uv sync

# 2. Seed your memory directory from the templates.
#    memory/ is gitignored — your real memories never leave the host.
cp -r memory.example memory

# 3. Create your .env from the example.
cp .env.example .env

# 4. Generate a bearer token.
python -c "import secrets; print(secrets.token_urlsafe(32))"
#    Copy the output and paste it into .env as:
#        MEMORY_TOKEN=<paste>

# 5. Start the server.
uv run python server.py
#    Listens on http://127.0.0.1:3333/mcp
```

The Inspector at `http://127.0.0.1:3333/` lets you call tools manually while
the server is running.

## Tools

- `list_memories(type?, scope?, include_archived?)`
- `read_memory(id_or_path)`
- `search_memories(query, type?, scope?, max_results?)`
- `write_memory(path, content)` — content must start with `---` frontmatter
- `delete_memory(id_or_path)`

## Connect a client

Pick the URL that matches where the client runs relative to the server:

| Setup | URL |
|---|---|
| Client on the same machine as the server | `http://127.0.0.1:3333/mcp` |
| Client on your LAN or tailnet | `http://<host>:3333/mcp` |
| ChatGPT.com / Claude.ai web / Mistral Le Chat | public HTTPS URL (see [Public exposure](#public-exposure)) |

The `<TOKEN>` below is the `MEMORY_TOKEN` you generated in step 4.

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

Both need a **public HTTPS URL** — see [Public exposure](#public-exposure).
Bearer auth is the awkward part on both, as of July 2026:

- **ChatGPT** — enable Developer Mode under **Settings → Security and login**
  (it moved from Connectors → Advanced), then add the connector. Setup is
  web-only; once added it works from the mobile apps. Plus/Pro/Business/
  Enterprise/Edu.
- **Claude.ai** — the custom-connector dialog offers OAuth Client ID/Secret by
  default. Passing a static bearer token needs **request header
  authentication**, which is a gated beta: "This feature is being slowly
  rolled out to customers; contact Anthropic for early access." If you don't
  have it, use Claude Code or Claude Desktop instead, which both support
  bearer headers today.

## Instructions for humans

Connecting the server is not enough. MCP tools only fire when the model
decides to call them, and a model with its own built-in memory will usually
reach for that instead — it will answer from local memory and never touch
this server. You have to tell it. Pick the strongest option your client
supports:

**Claude Code — use the hook.** Deterministic: it runs every session, no
model discretion involved. `hooks/session_start.py` calls `list_memories`
and injects the index via `additionalContext`.

```bash
# 1. Put the script somewhere stable and make it executable.
mkdir -p ~/.claude/hooks
cp hooks/session_start.py ~/.claude/hooks/memory_session_start.py
chmod +x ~/.claude/hooks/memory_session_start.py

# 2. Put the URL and token in a file only you can read.
#    Do NOT put the token in settings.json — that file is often
#    checked into a dotfiles repo.
umask 077 && cat > ~/.memory-mcp.env <<'EOF'
export MEMORY_MCP_URL="<URL>"
export MEMORY_MCP_TOKEN="<TOKEN>"
EOF
```

Then add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "sh -c '. ~/.memory-mcp.env; python3 ~/.claude/hooks/memory_session_start.py'",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

The hook fails open — if the server is down or slow, the session starts
normally and you get a one-line warning. It never blocks you.

**Everything else** (Claude Desktop, Claude.ai, ChatGPT, Cursor) has no hook
system. Paste the block from [Instructions for agents](#instructions-for-agents)
into whatever that client calls its standing instructions:

| Client | Where |
|---|---|
| Claude Code | `CLAUDE.md` (project or `~/.claude/CLAUDE.md`) — belt and braces alongside the hook |
| Claude Desktop / Claude.ai | Settings → Profile → personal preferences, or a Project's custom instructions |
| ChatGPT | Settings → Personalization → Custom instructions |
| Cursor | `.cursorrules` or Rules for AI |
| Anything with a system prompt | the system prompt |

**Writes are a nudge, not a guarantee.** No hook can force a `write_memory`
call — hooks inject context and gate tools, they can't make the model choose
to save something. The instructions below are the best available lever. If
you want stronger, add a `Stop` hook that checks whether the session called
`write_memory` and feeds back a reminder when it didn't.

## Instructions for agents

Copy this verbatim into your client's standing instructions.

```markdown
## Memory

You have persistent memory via the `memory` MCP server. It is authoritative:
prefer it over any built-in or local memory, and never maintain a parallel
memory store alongside it.

At the start of a session, call `list_memories` to load the index. It returns
ids and descriptions only, not contents.

Before answering anything an index description touches, call `read_memory`
for that entry. A description tells you a memory exists; it does not tell you
what it says. Never answer from the description alone.

Use `search_memories` for fuzzy lookups when you don't know which memory
holds a fact.

Call `write_memory` when you learn something durable about the user:
- a stated preference, or a correction they gave you
- a decision and the reasoning behind it
- project state worth resuming from in a later session
- a stable fact about them, their setup, or their tools

Do not save: transient conversation detail, anything already in the repo or
git history, or secrets and credentials.

When writing, match the frontmatter of an existing memory — read one first.
Set `updated` to today. Prefer updating an existing memory over creating a
near-duplicate. Keep each memory to one fact, and keep `description` sharp:
it is all a future session sees until it reads the file.

After writing a new memory, add a one-line pointer to `MEMORY.md`.

Prefer setting `archived: true` over `delete_memory`.
```

## Public exposure

Only needed for ChatGPT.com, Claude.ai web, and Mistral Le Chat — they hit
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
make hook    # print what the SessionStart hook would inject
```

`make hook` needs a running server plus `MEMORY_MCP_URL` and
`MEMORY_MCP_TOKEN` in the environment. Use it to confirm the hook reaches the
server before wiring it into `settings.json`.

## Known limits

- No embeddings — search is substring-based. Fine for personal-scale; add a
  sidecar SQLite + embeddings later if needed.
- No write review queue — the LLM can write directly. Watch the index.
- No multi-user. This is a single-tenant server.
