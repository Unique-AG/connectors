#!/usr/bin/env bash
# Install dependencies and agent skills in a fresh git worktree.
# Cursor (.cursor/worktrees.json) and Paseo (paseo.json) both call this.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
cd "$root"

for tool in pnpm uv; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'worktree-up: %s is missing. Enter the nix dev shell, then re-run bash scripts/worktree-up.sh\n' "$tool" >&2
    exit 1
  fi
done

pnpm install --frozen-lockfile
uvx --from poethepoet==0.49.0 poe install
bash "$root/agentic/skill-management/install-skills.sh"
