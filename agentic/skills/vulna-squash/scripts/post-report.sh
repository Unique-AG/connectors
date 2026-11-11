#!/usr/bin/env bash
set -euo pipefail

number=${1:?usage: post-report.sh <pr-number> <report-file>}
marker='<!-- vulna-squash-report -->'
[ "$(head -n 1 "$2")" = "$marker" ] || { echo "The report must start with ${marker}." >&2; exit 2; }

id=$(gh api --paginate "repos/{owner}/{repo}/issues/${number}/comments" \
  --jq ".[] | select(.body | startswith(\"${marker}\")) | .id" | head -n 1)
if [ -n "$id" ]; then
  gh api --method PATCH "repos/{owner}/{repo}/issues/comments/${id}" -F body=@"$2" > /dev/null
else
  gh pr comment "$number" --body-file "$2"
fi
