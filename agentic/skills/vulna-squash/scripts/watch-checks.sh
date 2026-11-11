#!/usr/bin/env bash
set -euo pipefail

number=${1:?usage: watch-checks.sh <pr-number>}
branch=$(gh pr view "$number" --json headRefName --jq .headRefName)
deadline=$((SECONDS + 2700))

while true; do
  if [ -n "$(gh run list --branch "$branch" --status action_required --json databaseId --jq '.[].databaseId')" ]; then
    echo held; exit 0
  fi
  buckets=$(gh pr checks "$number" --json bucket --jq '.[].bucket' || true)
  if grep -qxE 'fail|cancel' <<< "$buckets"; then echo red; exit 0; fi
  if [ -n "$buckets" ] && ! grep -qx pending <<< "$buckets"; then echo green; exit 0; fi
  if [ "$SECONDS" -ge "$deadline" ]; then echo timed_out; exit 0; fi
  sleep 240
done
