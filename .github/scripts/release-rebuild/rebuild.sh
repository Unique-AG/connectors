#!/usr/bin/env bash
set -euo pipefail

: "${1:?usage: rebuild.sh <service|all>...}"
here=$(cd "$(dirname "$0")" && pwd)
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

for service in $services; do
  if ! reason=$(bash "$here/rebuild-needed.sh" "$service"); then
    echo "::notice::${reason}"
    continue
  fi
  title="build(${service}): rebuild for operating system patches"
  body="This pull request rebuilds ${service}. It changes one date file and no code. The release build takes the newest operating system patches. GitHub holds the workflow runs on this pull request. Approve the runs. Then merge this pull request. Then merge the release pull request that release-please opens."
  if [ -n "${BODY_FILE:-}" ]; then body=$(< "$BODY_FILE"); fi
  branch="rebuild/${service}-${suffix}"
  file="services/${service}/deploy/rebuild-date"
  git switch --detach --quiet origin/main
  git switch --create "$branch" --quiet
  printf '%s\n' "$stamp" > "$file"
  git add "$file"
  git commit --quiet --message "$title"
  git push --quiet origin "$branch"
  gh pr create --base main --head "$branch" --title "$title" --label dependencies --label rebuild --body "$body"
done
