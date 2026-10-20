# MCP Skeleton

@../../packages/mcp-architecture/ARCHITECTURE.md

This MCP keeps the architecture every Python MCP in this repo shares. Read
[`packages/mcp-architecture/ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md)
before you write code here: `uv run pytest` checks most of it, and
`services/architecture-demo-mcp` holds a worked example of every part.

## Commands

```bash
# install
uv sync
# tests, contracts and folder rules
uv run pytest
uv run ruff format . && uv run ruff check .
uv run basedpyright
# serve on http://127.0.0.1:8000/mcp, after cp .env.example .env
uv run mcp-skeleton
```
