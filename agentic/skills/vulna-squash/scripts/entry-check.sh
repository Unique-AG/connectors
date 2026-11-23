#!/usr/bin/env bash
set -euo pipefail

number=${1:?usage: entry-check.sh <pr-number>}
reason=$(gh pr view "$number" --json state,labels,isCrossRepository | jq -r '
  (.labels | map(.name)) as $labels
  | [ (select(.state != "OPEN") | "The PR is not open."),
      (select(.isCrossRepository) | "The PR comes from a fork."),
      (select($labels | index("dependencies") | not) | "The PR lacks the label dependencies."),
      (select($labels | any(IN("ai-assisted", "human-required", "rebuild"))) | "The PR has the label ai-assisted, human-required or rebuild.") ]
  | first // empty')
if [ -n "$reason" ]; then echo "$reason"; exit 1; fi
