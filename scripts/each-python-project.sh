#!/usr/bin/env bash
# Run a command in every Python project, or in the folders PROJECTS names, and list where it failed.
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
