#!/usr/bin/env bash
# Every check the [CI] Python workflow runs on a service, in its order, so a run that passes here
# passes there. Usage: scripts/check-python-service.sh services/<service>
# biome comes from the repository's node_modules: run `pnpm install` once first.
set -euo pipefail

cd "${1:?usage: $0 <service-dir>}"

step() {
  echo "==> $*"
  "$@"
}

step uv sync --locked

# The generator imports the Python code of the service and needs no terraform binary.
if [ -f scripts/render-terraform-registry.py ]; then
  step uv run python scripts/render-terraform-registry.py --check
fi

# A service with [tool.mcp-openapi] commits the code generated from its vendored spec. This fails
# when the spec or the table changed and the code was not regenerated, or was edited by hand.
if grep -q '^\[tool\.mcp-openapi\]' pyproject.toml; then
  step uv run mcp-openapi-codegen --check
fi

step uv run ruff format --check .
step pnpm exec biome check . --no-errors-on-unmatched
step uv run ruff check .
step uv run basedpyright

# Only a service that keeps packages/mcp-architecture/ARCHITECTURE.md declares contracts.
if grep -q '^\[tool\.importlinter\]' pyproject.toml; then
  step uv run lint-imports
  # basedpyright honours a `# pyright:` comment that sets a file's mode or a report, whatever the
  # shared config says. Only `# pyright: ignore[rule]` on one line is left.
  echo "==> no file changes its type check"
  if grep -rnE --include='*.py' '#[[:space:]]*pyright:' src tests \
    | grep -vE '#[[:space:]]*pyright:[[:space:]]*ignore\['; then
    echo "Remove the comment above: a file keeps the type check of the whole MCP." >&2
    exit 1
  fi
fi

step uv run pytest
