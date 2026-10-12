#!/usr/bin/env bash
# Install dependencies and agent skills in a fresh git worktree.
# Cursor (.cursor/worktrees.json) and Paseo (paseo.json) both call this.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
cd "$root"

if ! command -v pnpm >/dev/null 2>&1; then
  printf 'worktree-up: pnpm is missing. Enter the nix dev shell, then re-run bash scripts/worktree-up.sh\n' >&2
  exit 1
fi

pnpm install --frozen-lockfile
bash "$root/agentic/skill-management/install-skills.sh"
