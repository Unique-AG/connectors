#!/usr/bin/env bash
set -euo pipefail

service=${1:?usage: rebuild-plan.sh <service>}
title="build(${service}): rebuild for operating system patches"
release_branch="release-please--branches--main--components--${service}"
cd "$(git rev-parse --show-toplevel)"

release_pr=""
rebuild_pr=""
rebuild_branch=""

plan() {
  jq -n --arg action "$1" --arg reason "$2" --arg rebuild_pr "$rebuild_pr" --arg rebuild_branch "$rebuild_branch" --arg release_pr "$release_pr" \
    '{action: $action, reason: $reason, rebuild_pr: ($rebuild_pr | tonumber? // null), rebuild_branch: ($rebuild_branch | select(. != "") // null), release_pr: ($release_pr | tonumber? // null)}'
  exit 0
}

released=$(jq --arg path "services/${service}" 'has($path)' .release-please-manifest.json)
[ "$released" = true ] || plan none "${service} is not a released service."

release_pr=$(gh pr list --state open --limit 200 --label "autorelease: pending" --json number,headRefName,isCrossRepository \
  | jq -r --arg branch "$release_branch" 'map(select(.headRefName == $branch and (.isCrossRepository | not))) | .[0].number // empty')
rebuild=$(gh pr list --state open --limit 200 --label rebuild --json number,title,headRefName,isCrossRepository \
  | jq -r --arg title "$title" 'map(select(.title == $title and (.headRefName | startswith("rebuild/")) and (.isCrossRepository | not))) | .[0] | if . then "\(.number) \(.headRefName)" else empty end')
read -r rebuild_pr rebuild_branch <<< "$rebuild"

if [ -n "$release_pr" ] && [ -n "$rebuild_pr" ]; then
  plan close "${service} has the open release pull request #${release_pr}. Its release rebuilds the image, so the rebuild pull request #${rebuild_pr} is not needed."
fi
if [ -n "$release_pr" ]; then
  plan none "${service} has the open release pull request #${release_pr}. Its release rebuilds the image."
fi
if [ -n "$rebuild_pr" ]; then
  plan refresh "${service} has the open rebuild pull request #${rebuild_pr} and no open release pull request."
fi
plan open "${service} has no open release pull request and no open rebuild pull request."
