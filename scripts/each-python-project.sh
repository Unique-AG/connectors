#!/usr/bin/env bash
# Run a command in every Python project under packages/ and services/, or in the folders PROJECTS
# names, one after another, and end with the list of projects it failed in. Each project has its
# own uv.lock and .venv.
# Usage: bash scripts/each-python-project.sh uv sync --locked
set -uo pipefail

cd "$(dirname "$0")/.."

if [[ -n "${PROJECTS:-}" ]]; then
  read -ra projects <<<"$PROJECTS"
else
  projects=()
  for pyproject in packages/*/pyproject.toml services/*/pyproject.toml; do
    projects+=("$(dirname "$pyproject")")
  done
fi

failed=()
for project in "${projects[@]}"; do
  printf '\n== %s: %s\n' "$project" "$*"
  (cd "$project" && "$@") || failed+=("$project")
done

if ((${#failed[@]})); then
  printf '\nFailed in: %s\n' "${failed[*]}" >&2
  exit 1
fi
