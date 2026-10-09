#!/bin/bash
# Refresh .claude/skills from the canonical agentic/skills trees.
# Use this after editing a skill, without waiting for the next git pull.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
exec bash "$root/agentic/skill-management/install-skills.sh"
