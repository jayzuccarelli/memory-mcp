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
plugin/                # Claude Code plugin; install this on each machine
  .mcp.json            # registers the stdio proxy below
  bin/proxy.py         # bridges Claude Code to the HTTP server
  bin/setup.py         # writes the config from one connection string
  lib/config.py        # shared config, read by every part
  lib/client.py        # minimal MCP client shared by the hooks
  hooks/mirror_write.py  # keeps local memory writes in sync with the server
  commands/setup.md    # the /memory:setup slash command
  hooks/session_start.py
.claude-plugin/        # marketplace manifest, so the repo is installable
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

This runs the server on one machine. Every client you connect later (Claude
Code on your laptop, ChatGPT, Claude Desktop) talks to this one server, which
is the point: one memory, many machines.

It binds to `127.0.0.1` by default, so only that machine can reach it. To use
it from a second machine, set `HOST=0.0.0.0` in `.env` for LAN/tailnet access,
or put it behind HTTPS as described in [Public exposure](#public-exposure).

```bash
# 1. Install uv if you don't have it. It brings its own Python, so this is
#    the only prerequisite. See https://docs.astral.sh/uv for other methods.
curl -LsSf https://astral.sh/uv/install.sh | sh

#    uv lands in ~/.local/bin, which your current shell may not have on PATH
#    yet. This makes it visible without opening a new terminal.
source $HOME/.local/bin/env

# 2. Get the code.
git clone https://github.com/jayzuccarelli/memory-mcp.git
cd memory-mcp

# 3. Install deps.
uv sync

# 4. Seed your memory directory from the templates.
#    memory/ is gitignored, so your real memories never leave the host.
cp -r memory.example memory

# 5. Create your .env from the example.
cp .env.example .env

# 6. Generate a bearer token and write it into .env. Safe to skip if you
#    already have one; this refuses to append a second.
grep -q '^MEMORY_TOKEN=.\+' .env || \
  uv run python -c "import secrets; print('MEMORY_TOKEN=' + secrets.token_urlsafe(32))" >> .env

# 7. Start the server.
uv run python server.py
```

On startup it prints the line you need to connect a client:

```
Connect a client by running this in Claude Code:
  /memory:setup memory://SGVsbG8...@http://127.0.0.1:3333/mcp
```

That one string carries the address and the token together. If the server sits
behind a proxy or tunnel, swap in the public endpoint, scheme included:
`memory://<same-token>@https://your-host/mcp`.

The server speaks MCP over streamable HTTP at `/mcp` and serves no browser UI:
`/` returns 404. Start it with `DEBUG=1` to enable mcp-use's built-in inspector
at `/inspector`, or point the standalone
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

The `<TOKEN>` below is the `MEMORY_TOKEN` you generated in step 6.

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

Both need a **public HTTPS URL**; see [Public exposure](#public-exposure).
Bearer auth is the awkward part on both, as of July 2026:

- **ChatGPT**: needs Developer Mode, which is in beta and has moved around
  the settings UI more than once. Check OpenAI's [Developer Mode
  article](https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt-beta)
  for the current location, which plans include it, and whether write tools
  are available on yours. Setup is web-only.
- **Claude.ai**: the custom-connector dialog offers OAuth Client ID/Secret by
  default. Passing a static bearer token needs **request header
  authentication**, which is a gated beta: "This feature is being slowly
  rolled out to customers; contact Anthropic for early access." If you don't
  have it, use Claude Code or Claude Desktop instead, which both support
  bearer headers today.

## Instructions for humans

Connecting the server is not enough. MCP tools only fire when the model
decides to call them, and a model with its own built-in memory will usually
reach for that instead; it will answer from local memory and never touch
this server. You have to tell it. Pick the strongest option your client
supports:

**Claude Code: install the plugin.** It ships both halves: the connection to
your server *and* a `SessionStart` hook that injects your memory index into
every session. The hook is deterministic: it runs whether or not the model
feels like calling a tool.

Three lines, nothing to edit by hand:

```
/plugin marketplace add jayzuccarelli/memory-mcp
/plugin install memory@memory-mcp
/memory:setup <the memory:// string your server printed>
```

Then `/reload-plugins`. Verify with `/mcp` (expect `memory` connected) and by
asking a fresh session what memories it has. It should answer without calling
a tool, because the index is already in context.

**Repeat this on every machine you work from.** The server runs in one place;
the plugin is the client half and is installed per machine. Once two machines
are set up they read and write the same memories, so something you tell Claude
on your laptop is there on your desktop.

`/memory:setup` writes `~/.config/memory-mcp/config.json` with owner-only
permissions. Nothing goes into your shell profile and nothing goes into
`settings.json`, which is commonly symlinked into a public dotfiles repo. If
you prefer, `MEMORY_MCP_URL` and `MEMORY_MCP_TOKEN` in the environment still
override the file.

The hook fails open. If the server is down or slow, the session starts normally
with a one-line warning. It never blocks you.

**Everything else** (Claude Desktop, Claude.ai, ChatGPT, Cursor) has no hook
system. Paste the block from [Instructions for agents](#instructions-for-agents)
into whatever that client calls its standing instructions:

| Client | Where |
|---|---|
| Claude Code | `CLAUDE.md` (project or `~/.claude/CLAUDE.md`), belt and braces alongside the hook |
| Claude Desktop / Claude.ai | Settings → Profile → personal preferences, or a Project's custom instructions |
| ChatGPT | Settings → Personalization → Custom instructions |
| Cursor | `.cursorrules` or Rules for AI |
| Anything with a system prompt | the system prompt |

### Writes, and the two-store problem

Claude Code has its own file-based memory. Left alone, "remember this" lands in
whichever store the model reaches for, the two drift apart, and the memory you
saved on your laptop isn't on your desktop, which is the whole thing this is
supposed to fix.

The plugin closes that with a hook on local memory writes. Set `write_mode` in
`~/.config/memory-mcp/config.json`:

| mode | Claude Code saves a memory locally | model calls `write_memory` |
|---|---|---|
| `mirror` *(default)* | saved locally **and** copied to the server | goes to the server |
| `redirect` | blocked, with a message telling it to use the server | goes to the server |
| `off` | stays local, server never sees it | goes to the server |

`mirror` keeps both stores working and is the safe default. `redirect` makes the
server the only store, which is stricter but overrides a built-in Claude Code
feature. `off` is the pre-plugin behavior.

The hook fails open in every mode: if the server is unreachable your local write
still succeeds, and you get a one-line warning.

Other clients have no hook system, so for those the instructions below are the
only lever.

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

Use `search_memories` when you don't know which memory holds a fact. It is
case-insensitive substring matching, not semantic search, so try the literal
words you expect to appear.

Call `write_memory` when you learn something durable about the user:
- a stated preference, or a correction they gave you
- a decision and the reasoning behind it
- project state worth resuming from in a later session
- a stable fact about them, their setup, or their tools

Do not save: transient conversation detail, anything already in the repo or
git history, or secrets and credentials.

When writing, match the frontmatter of an existing memory; read one first.
Set `updated` to today. Prefer updating an existing memory over creating a
near-duplicate. Keep each memory to one fact, and keep `description` sharp:
it is all a future session sees until it reads the file.

After writing a new memory, add a one-line pointer to `MEMORY.md`.

Prefer setting `archived: true` over `delete_memory`.
```

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
make hook    # print what the SessionStart hook would inject
```

`make hook` needs a running server and a configured client: either
`/memory:setup` already run, or `MEMORY_MCP_URL` and `MEMORY_MCP_TOKEN` in the
environment. Use it to confirm the hook reaches the server. The hook is
registered by the plugin via `plugin/hooks/hooks.json`; you never edit
`settings.json`.

## Known limits

- No embeddings: search is substring-based. Fine for personal-scale; add a
  sidecar SQLite + embeddings later if needed.
- No write review queue: the LLM can write directly. Watch the index.
- No multi-user. This is a single-tenant server.
