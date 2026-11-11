#!/usr/bin/env bash
set -euo pipefail

service=${1:?usage: rebuild-needed.sh <service>}
title="build(${service}): rebuild for operating system patches"
branch="release-please--branches--main--components--${service}"

covered() {
  echo "$1"
  exit 10
}

release_prs=$(gh pr list --state open --limit 200 --label "autorelease: pending" --json headRefName,isCrossRepository \
  --jq "map(select(.headRefName == \"${branch}\" and (.isCrossRepository | not))) | length")
[ "$release_prs" = 0 ] || covered "${service} has an open release pull request. Its release rebuilds the image."

rebuild_titles=$(gh pr list --state open --limit 200 --label rebuild --json title --jq '.[].title')
if grep -qxF "$title" <<< "$rebuild_titles"; then covered "${service} has an open rebuild pull request."; fi
