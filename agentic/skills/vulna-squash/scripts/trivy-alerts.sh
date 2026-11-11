#!/usr/bin/env bash
set -euo pipefail

run=$(gh run list --workflow security-trivy-nightly.yaml --branch main --limit 1 --json status,conclusion,createdAt --jq '.[0]')
if ! jq -e '(now - (.createdAt | fromdateiso8601)) < 86400' <<< "$run" > /dev/null; then
  echo "The latest nightly scan is older than 24 hours." >&2; exit 1
fi
if ! jq -e '.status == "completed" and (.conclusion | IN("success", "failure"))' <<< "$run" > /dev/null; then
  echo "The latest nightly scan did not finish: $(jq -r '.status + " " + .conclusion' <<< "$run")." >&2; exit 1
fi

gh api --paginate 'repos/{owner}/{repo}/code-scanning/alerts?state=open&tool_name=Trivy&per_page=100' \
  | jq -s 'add | map(select(.rule.security_severity_level | IN("critical", "high")) | select(.most_recent_instance.category | startswith("trivy-config") | not))'
