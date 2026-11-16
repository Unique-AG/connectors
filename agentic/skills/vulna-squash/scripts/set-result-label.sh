#!/usr/bin/env bash
set -euo pipefail

number=${1:?usage: set-result-label.sh <pr-number> ai-assisted|human-required}
case "${2:-}" in
  ai-assisted) other=human-required ;;
  human-required) other=ai-assisted ;;
  *) echo "usage: set-result-label.sh <pr-number> ai-assisted|human-required" >&2; exit 2 ;;
esac
gh pr edit "$number" --add-label "$2" --remove-label "$other"
