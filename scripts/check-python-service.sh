#!/usr/bin/env bash
# Every check the [CI] Python workflow runs on a service, in its order, so a run that passes here
# passes there. Usage: scripts/check-python-service.sh services/<service>
# biome comes from the repository's node_modules: run `pnpm install` once first.
#
# Every check runs even after one fails, so one run lists all there is to fix. Each failure names
# the command that fixes it. In GitHub Actions, each check is a collapsible group of the log and a
# failure is an error annotation on the run.
set -uo pipefail

cd "${1:?usage: $0 <service-dir>}" || exit 1

failed=()

in_github_actions() {
  [ -n "${GITHUB_ACTIONS:-}" ]
}

# check <name> <how to fix it> <command...>
check() {
  local name=$1 fix=$2
  shift 2
  if in_github_actions; then
    echo "::group::$name"
  else
    echo "==> $name: $*"
  fi
  local status=0
  "$@" || status=$?
  if in_github_actions; then
    echo "::endgroup::"
  fi
  if [ "$status" -ne 0 ]; then
    failed+=("$name")
    if in_github_actions; then
      echo "::error title=$name failed::$fix"
    else
      echo "!! $name failed. $fix" >&2
    fi
  fi
}

# basedpyright honours a `# pyright:` comment that sets a file's mode or a report, whatever the
# shared config says. Only `# pyright: ignore[rule]` on one line is left.
# The verdict comes from the lines found, not the pipeline's status, which pipefail would take
# from the first grep.
no_file_changes_its_type_check() {
  local folders=() folder found
  for folder in src tests; do
    if [ -d "$folder" ]; then
      folders+=("$folder")
    fi
  done
  if [ ${#folders[@]} -eq 0 ]; then
    return 0
  fi
  found=$(grep -rnE --include='*.py' '#[[:space:]]*pyright:' "${folders[@]}" \
    | grep -vE '#[[:space:]]*pyright:[[:space:]]*ignore\[')
  if [ -n "$found" ]; then
    echo "$found"
    return 1
  fi
}

check "Install" "Run \`uv lock\` and commit uv.lock." uv sync --locked
if [ ${#failed[@]} -ne 0 ]; then
  exit 1
fi

if [ -f scripts/render-terraform-registry.py ]; then
  check "Terraform registry" \
    "Run \`uv run python scripts/render-terraform-registry.py\` and commit the result." \
    uv run python scripts/render-terraform-registry.py --check
fi

# A service with [tool.mcp-openapi] commits the code generated from its vendored spec.
if grep -q '^\[tool\.mcp-openapi\]' pyproject.toml; then
  check "OpenAPI codegen" \
    "Run \`uv run mcp-openapi-codegen\` and commit the result. Never edit the generated files." \
    uv run mcp-openapi-codegen --check
fi

check "Format" "Run \`uv run ruff format .\`." uv run ruff format --check .
check "Biome" "Run \`pnpm exec biome check --write .\`." \
  pnpm exec biome check . --no-errors-on-unmatched
check "Lint" "Run \`uv run ruff check --fix .\`, then fix by hand what it lists." \
  uv run ruff check .
check "Types" "Fix what \`uv run basedpyright\` lists. Never turn a report down." \
  uv run basedpyright

# Only a service that keeps packages/mcp-architecture/ARCHITECTURE.md declares contracts.
if grep -q '^\[tool\.importlinter\]' pyproject.toml; then
  check "Imports" \
    "Move the import named above to the layer or top level ARCHITECTURE.md gives it. Never loosen a contract." \
    uv run lint-imports
  check "Type check comments" \
    "Remove the \`# pyright:\` comment listed above; a file keeps the type check of the whole MCP." \
    no_file_changes_its_type_check
  # Outside pytest, so a conftest.py cannot skip, xfail or deselect it.
  check "What a client sees" \
    "Fix what \`uv run mcp-architecture-check\` lists. If only the tool surface changed and you meant it, run \`uv run mcp-architecture-check --update\`." \
    uv run mcp-architecture-check
fi

check "Tests" "Fix the failing tests." uv run pytest

if [ ${#failed[@]} -ne 0 ]; then
  echo "Failed: ${failed[*]}" >&2
  exit 1
fi
echo "Every check passed."
