#!/usr/bin/env bash
set -euo pipefail

number=${1:?usage: set-pr-scope.sh <pr-number>}
cd "$(git rev-parse --show-toplevel)"
scope=$(gh api --paginate "repos/{owner}/{repo}/pulls/${number}/files" --jq '.[].filename' | node .github/scripts/deps-nightly/scope.cli.mjs)
title=$(gh pr view "$number" --json title --jq .title)
gh pr edit "$number" --title "$(sed -E "s/^([a-z]+)(\([^)]*\))?(!?):/\1(${scope})\3:/" <<< "$title")"
