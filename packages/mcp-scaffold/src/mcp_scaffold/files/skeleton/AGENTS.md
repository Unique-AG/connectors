# MCP Skeleton

@../../packages/mcp-architecture/ARCHITECTURE.md

This MCP keeps the architecture every Python MCP in this repo shares. Read
[`packages/mcp-architecture/ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md)
before you write code here: ruff, basedpyright and import-linter check most of it.

## Commands

```bash
# install
uv sync
# every check CI runs, in its order
bash ../../scripts/check-python-service.sh .
# or one at a time
uv run ruff format . && uv run ruff check .
uv run basedpyright
uv run lint-imports
uv run mcp-architecture-check
uv run pytest
# serve on http://127.0.0.1:8000/mcp, after cp .env.example .env
uv run mcp-skeleton
```
