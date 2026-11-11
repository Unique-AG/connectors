#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
service=${1:?usage: audit.sh <service>}
[[ $service =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "error: $service is not a service name" >&2; exit 1; }

git fetch -q --tags origin main
version=$(git show origin/main:.release-please-manifest.json | jq -r --arg p "services/$service" '.[$p] // empty')
[ -n "$version" ] || { echo "error: the manifest has no version for $service" >&2; exit 1; }
tag="$service@$version"
if git rev-parse -q --verify "refs/tags/$tag" > /dev/null; then
  baseline=$tag
  label=$tag
elif [ "$version" = 0.0.0 ]; then
  baseline=$(git hash-object -t tree /dev/null)
  label="first release"
else
  echo "error: the tag $tag does not exist" >&2
  exit 1
fi

dir=services/$service
chart=$dir/deploy/helm-charts/$service/Chart.yaml
shared=$(git show origin/main:"$dir/deploy/Dockerfile" 2> /dev/null | grep -oE '^COPY packages/[A-Za-z0-9_-]+' | cut -d' ' -f2 || true)
paths=("$dir")
for package in $shared; do paths+=("$package"); done
files=$(git diff --name-only "$baseline" origin/main -- "${paths[@]}" | grep -Ev '(/tests?/|\.test\.|\.spec\.|CHANGELOG|\.md$|\.lock$|pnpm-lock|\.terraform\.lock\.hcl|^services/[^/]+/features/|/scripts/)' || true)

base_pin() {
  git show "$1:$chart" 2> /dev/null | awk '/name: base/ { f = 1 } f && /version:/ { print $2; exit }' || true
}

section() {
  printf '== %s\n' "$1"
  grep -E "$2" <<< "$files" || echo "(none)"
}

printf '# %s: %s to origin/main\n' "$service" "$label"
section "config" '/(config|settings)[^/]*\.(py|ts)$|/config/|\.env\.example$'
section "chart" '/deploy/helm-charts/'
section "terraform" '/deploy/terraform/'
section "migrations" '/migrations/'
section "image" '/deploy/Dockerfile$'
printf '== added lines that read the environment\n'
if [ -n "$files" ]; then
  git diff -U0 "$baseline" origin/main -- $files | grep -E '^\+[^+].*(Settings\(|BaseSettings|process\.env|os\.environ|os\.getenv|validation_alias|env_prefix)' || echo "(none)"
else
  echo "(none)"
fi
printf '== base chart pin\n%s -> %s\n' "$(base_pin "$baseline")" "$(base_pin origin/main)"
