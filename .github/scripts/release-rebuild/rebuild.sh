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
  [ "$(jq --arg path "services/${service}" 'has($path)' .release-please-manifest.json)" = true ] \
    || { echo "::error::${service} is not a released service."; exit 1; }
done

git fetch --quiet origin +refs/heads/main:refs/remotes/origin/main
stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
suffix=$(date -u +%Y%m%d%H%M%S)
gh label create rebuild --color fbca04 --description "Rebuilds an image for operating system patches" || true
tree=$(mktemp -d)
trap 'git worktree remove --force "$tree" 2> /dev/null || true' EXIT

for service in $services; do
  plan=$(bash "$here/rebuild-plan.sh" "$service")
  action=$(jq -r .action <<< "$plan")
  reason=$(jq -r .reason <<< "$plan")
  rebuild_pr=$(jq -r '.rebuild_pr // empty' <<< "$plan")
  rebuild_branch=$(jq -r '.rebuild_branch // empty' <<< "$plan")
  case "$action" in
    none)
      echo "::notice::${reason}"
      continue
      ;;
    close)
      gh pr close "$rebuild_pr" --delete-branch --comment "$reason"
      continue
      ;;
  esac
  title="build(${service}): rebuild for operating system patches"
  body=${custom_body:-"This pull request rebuilds ${service}. It changes one date file and no code. The release build takes the newest operating system patches. GitHub holds the workflow runs on this pull request. Approve the runs. Then merge this pull request. Then merge the release pull request that release-please opens."}
  file="services/${service}/deploy/rebuild-date"
  if [ "$action" = refresh ]; then
    branch=$rebuild_branch
    git fetch --quiet origin "+refs/heads/${branch}:refs/remotes/origin/${branch}"
    git worktree add --quiet -B "$branch" "$tree" "origin/${branch}"
  else
    branch="rebuild/${service}-${suffix}"
    git worktree add --quiet -b "$branch" "$tree" origin/main
  fi
  printf '%s\n' "$stamp" > "$tree/$file"
  git -C "$tree" add "$file"
  git -C "$tree" commit --quiet --message "$title"
  git -C "$tree" push --quiet origin "$branch"
  git worktree remove --force "$tree"
  git branch --quiet -D "$branch"
  if [ "$action" = open ]; then
    gh pr create --base main --head "$branch" --title "$title" --label dependencies --label rebuild --body "$body"
  fi
done
