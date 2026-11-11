#!/usr/bin/env bash
set -euo pipefail

service=${1:?usage: rebuild-needed.sh <service>}
title="build(${service}): rebuild for operating system patches"

release_prs=$(gh pr list --state open --head "release-please--branches--main--components--${service}" --json number --jq length)
if [ "$release_prs" != 0 ]; then
  echo "${service} has an open release pull request. Its release rebuilds the image."
  exit 1
fi

if gh pr list --state open --label rebuild --json title --jq '.[].title' | grep -qxF "$title"; then
  echo "${service} has an open rebuild pull request."
  exit 1
fi
