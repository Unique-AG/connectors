#!/usr/bin/env bash
set -euo pipefail

service=${1:?usage: rebuild-needed.sh <service>}
title="build(${service}): rebuild for operating system patches"
branch="release-please--branches--main--components--${service}"
cd "$(git rev-parse --show-toplevel)"

covered() {
  echo "$1"
  exit 10
}

released=$(jq --arg path "services/${service}" 'has($path)' .release-please-manifest.json)
[ "$released" = true ] || covered "${service} is not a released service."

release_pr=$(gh pr list --state open --limit 200 --label "autorelease: pending" --json number,headRefName,isCrossRepository \
  --jq "map(select(.headRefName == \"${branch}\" and (.isCrossRepository | not))) | .[0].number // empty")
[ -z "$release_pr" ] || covered "${service} has the open release pull request #${release_pr}. Its release rebuilds the image."

rebuild_titles=$(gh pr list --state open --limit 200 --label rebuild --json title --jq '.[].title')
if grep -qxF "$title" <<< "$rebuild_titles"; then covered "${service} has an open rebuild pull request."; fi
