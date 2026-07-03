.PHONY: check lint smoke run sync

# One-shot verifier — lint + import + tool-registry check.
# Run this before shipping any change.
check: lint smoke

sync:
	uv sync

lint:
	uv run --with ruff ruff check .
	uv run --with ruff ruff format --check .

# Imports server.py against memory.example/ (no real memories needed)
# and confirms all 5 tools registered with the MCP server.
smoke:
	MEMORY_DIR=$(CURDIR)/memory.example uv run python -c "\
import asyncio, server; \
tools = asyncio.run(server.server.list_tools()); \
names = sorted(t.name for t in tools); \
expected = ['delete_memory','list_memories','read_memory','search_memories','write_memory']; \
assert names == expected, f'tool drift: got {names}, want {expected}'; \
print(f'smoke ok: {server.server.name} with {len(names)} tools')"

run:
	uv run python server.py
