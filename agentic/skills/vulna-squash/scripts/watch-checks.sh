#!/usr/bin/env bash
set -euo pipefail

number=${1:?usage: watch-checks.sh <pr-number>}
deadline=$((SECONDS + 2700))

while true; do
  if branch=$(gh pr view "$number" --json headRefName --jq .headRefName) \
    && sha=$(gh pr view "$number" --json headRefOid --jq .headRefOid) \
    && held=$(gh run list --branch "$branch" --commit "$sha" --status action_required --json databaseId --jq '.[].databaseId'); then
    if [ -n "$held" ]; then echo held; exit 0; fi
    checks=$(gh pr checks "$number" --json name,bucket 2> /dev/null || true)
    checks=${checks:-[]}
    if jq -e 'any(.[]; .bucket | IN("fail", "cancel"))' <<< "$checks" > /dev/null; then echo red; exit 0; fi
    if jq -e 'any(.[]; .name == "gatekeeper" and .bucket == "pass") and all(.[]; .bucket != "pending")' <<< "$checks" > /dev/null; then echo green; exit 0; fi
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then echo timed_out; exit 0; fi
  sleep 240
done
