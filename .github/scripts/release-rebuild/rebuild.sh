#!/usr/bin/env bash
set -euo pipefail

: "${1:?usage: rebuild.sh <service|all>...}"
here=$(cd "$(dirname "$0")" && pwd)
custom_body=""
if [ -n "${BODY_FILE:-}" ]; then custom_body=$(< "$BODY_FILE"); fi
cd "$(git rev-parse --show-toplevel)"

if [ "$1" = all ]; then
  services=$(jq -r 'keys[] | ltrimstr("services/")' .release-please-manifest.json)
else
  services=$(printf '%s\n' "$@" | tr ', ' '\n\n' | sed '/^$/d')
fi

for service in $services; do
  jq -e --arg path "services/${service}" 'has($path)' .release-please-manifest.json > /dev/null \
    || { echo "::error::${service} is not a released service."; exit 1; }
done

git fetch --quiet origin main
stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
suffix=$(date -u +%Y%m%d%H%M%S)
gh label create rebuild --color fbca04 --description "Rebuilds an image for operating system patches" || true
tree=$(mktemp -d)
trap 'git worktree remove --force "$tree" 2> /dev/null || true' EXIT

for service in $services; do
  status=0
  reason=$(bash "$here/rebuild-needed.sh" "$service") || status=$?
  if [ "$status" = 10 ]; then
    echo "::notice::${reason}"
    continue
  fi
  [ "$status" = 0 ] || exit "$status"
  title="build(${service}): rebuild for operating system patches"
  body=${custom_body:-"This pull request rebuilds ${service}. It changes one date file and no code. The release build takes the newest operating system patches. GitHub holds the workflow runs on this pull request. Approve the runs. Then merge this pull request. Then merge the release pull request that release-please opens."}
  branch="rebuild/${service}-${suffix}"
  file="services/${service}/deploy/rebuild-date"
  git worktree add --quiet -b "$branch" "$tree" origin/main
  printf '%s\n' "$stamp" > "$tree/$file"
  git -C "$tree" add "$file"
  git -C "$tree" commit --quiet --message "$title"
  git -C "$tree" push --quiet origin "$branch"
  git worktree remove --force "$tree"
  git branch --quiet -D "$branch"
  gh pr create --base main --head "$branch" --title "$title" --label dependencies --label rebuild --body "$body"
done
