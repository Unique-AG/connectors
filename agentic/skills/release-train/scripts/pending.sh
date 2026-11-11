#!/usr/bin/env bash
set -euo pipefail

git fetch -q origin main
options=$(git show origin/main:.github/workflows/release-dev.yaml | sed -n '/options:/,/^permissions:/p' | sed -n 's/^ *- //p')

printf 'pr\tservice\tpending\tlast_release\tdispatch\treason\n'
gh pr list --repo Unique-AG/connectors --state open --label "autorelease: pending" --limit 1000 \
  --json number,headRefName,title --jq '.[] | [.number, .headRefName, .title] | @tsv' |
  while IFS=$'\t' read -r number branch title; do
    service=${branch##*--components--}
    pending=${title##* }
    if [[ $branch != *--components--* || ! $service =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
      printf '%s\t%s\t%s\t-\tno\tbranch names no component\n' "$number" "$branch" "$pending"
      continue
    fi
    last=$(git show origin/main:.release-please-manifest.json | jq -r --arg p "services/$service" '.[$p] // "-"')
    reason=ok
    dispatch=yes
    if ! grep -qx "$service" <<< "$options"; then
      dispatch=no
      reason="not in the service list of the Dev Build workflow"
    elif [ "$last" = "-" ]; then
      dispatch=no
      reason="no version in the manifest"
    elif ! git cat-file -e "origin/main:services/$service/deploy/helm-charts/$service/Chart.yaml" 2> /dev/null ||
      ! git cat-file -e "origin/main:services/$service/deploy/Dockerfile" 2> /dev/null; then
      dispatch=no
      reason="no Helm chart or no Dockerfile on main"
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$number" "$service" "$pending" "$last" "$dispatch" "$reason"
  done
