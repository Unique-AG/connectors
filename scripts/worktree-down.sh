#!/usr/bin/env bash
# Teardown hook for a git worktree. Cursor and Paseo both call this.
# Dependencies and .claude/skills live in the worktree directory, which the
# agent removes. core.hooksPath belongs to the clone and stays as it is.
set -euo pipefail
