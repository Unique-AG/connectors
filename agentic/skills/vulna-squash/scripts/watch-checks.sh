#!/usr/bin/env bash
set -euo pipefail

number=${1:?usage: watch-checks.sh <pr-number>}
deadline=$((SECONDS + 2700))

bounded() {
  if command -v timeout > /dev/null; then timeout "$(( deadline - SECONDS > 1 ? deadline - SECONDS : 1 ))" "$@"; else "$@"; fi
}

while true; do
  if branch=$(bounded gh pr view "$number" --json headRefName --jq .headRefName) \
    && sha=$(bounded gh pr view "$number" --json headRefOid --jq .headRefOid) \
    && held=$(bounded gh run list --branch "$branch" --commit "$sha" --status action_required --json databaseId --jq '.[].databaseId'); then
    if [ -n "$held" ]; then echo held; exit 0; fi
    checks=$(bounded gh pr checks "$number" --json name,bucket 2> /dev/null || true)
    checks=${checks:-[]}
    if jq -e 'any(.[]; .bucket | IN("fail", "cancel"))' <<< "$checks" > /dev/null; then echo red; exit 0; fi
    if jq -e 'any(.[]; .name == "gatekeeper" and .bucket == "pass") and all(.[]; .bucket != "pending" or (.name | startswith("Cursor Automation")))' <<< "$checks" > /dev/null; then echo green; exit 0; fi
  fi
  left=$((deadline - SECONDS))
  if [ "$left" -le 0 ]; then echo timed_out; exit 0; fi
  sleep $(( left < 240 ? left : 240 ))
done
