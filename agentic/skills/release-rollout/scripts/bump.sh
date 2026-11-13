#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
pin="$here/../../bump-service/scripts/set-pin.sh"
usage() {
  echo "usage: bump.sh monorepo <service> <version> <cluster> <env>" >&2
  echo "       bump.sh infrastructure <service> <version> [path-filter]" >&2
  echo "env:   OPEN=1 pushes the prepared branch and opens the PR; NOTES_FILE=<file> adds lines to the PR body" >&2
  exit 2
}
[ $# -ge 3 ] || usage
target=$1 service=$2 version=$3
[[ $service =~ ^[a-z0-9][a-z0-9-]*$ && $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage

sha=$(git ls-remote https://github.com/Unique-AG/connectors.git "refs/tags/$service@$version^{}" "refs/tags/$service@$version" | awk '{ print $1 }' | tail -1)
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo "error: the tag $service@$version does not exist" >&2; exit 1; }

cd "$("$here/clone.sh" "$target")"
case $target in
  monorepo)
    [ $# -eq 5 ] || usage
    cluster=$4 env=$5
    [[ $cluster =~ ^[a-z0-9]+$ && $env =~ ^[a-z0-9]+$ ]] || usage
    files=$(git grep -l "x-$service-version" -- "gitops-resources/argocd/clusters/$cluster/$env" || true)
    [ -n "$files" ] && [ "$(wc -l <<< "$files")" -eq 1 ] || { echo "error: expected one $service app spec in $cluster/$env" >&2; exit 1; }
    remote=Unique-AG/monorepo base=master branch="bump-$service-$version-$cluster-$env"
    scope=connectors
    if [[ $service == *-mcp ]]; then scope=mcp; fi
    title="chore($scope): bump $service to $version in $cluster/$env"
    where="the $cluster/$env ArgoCD app spec"
    ;;
  infrastructure)
    filter=${4:-}
    [[ $filter =~ ^[A-Za-z0-9/_.-]*$ ]] || usage
    files=$(git grep -l "x-$service-version" -- providers | grep -F -- "$filter" || true)
    [ -n "$files" ] || { echo "error: no $service pin in providers matches '$filter'" >&2; exit 1; }
    remote=Unique-AG/infrastructure base=main branch="chore/bump-$service-$version${filter:+-$(tr '/' '-' <<< "$filter")}"
    title="chore(cloud/azure): bump $service to $version for ${filter:-all tenants}"
    where="the Terraform module pins of ${filter:-all tenants}"
    ;;
  *) usage ;;
esac

if [ "${OPEN:-0}" = 1 ]; then
  git rev-parse -q --verify "refs/heads/$branch" > /dev/null || { echo "error: run without OPEN=1 first" >&2; exit 1; }
  body=$(mktemp)
  old=$(git show "origin/$base:$(head -1 <<< "$files")" | grep -oE "$service@[0-9][0-9A-Za-z.-]*" | head -1 | cut -d@ -f2 || true)
  {
    echo "## Summary"
    echo "- Changes $service from ${old:-dev} to $version in $where."
    if [ -s "${NOTES_FILE:-}" ]; then cat "$NOTES_FILE"; fi
    echo
    echo "## Test plan"
    if [ "$target" = monorepo ] && grep -q 'autoSync: false' "$files"; then
      echo "- [ ] Sync the app by hand after the merge. The app has autoSync off."
    elif [ "$target" = monorepo ]; then
      echo "- [ ] ArgoCD syncs the new pin after the merge."
    else
      echo "- [ ] The Terraform plan shows only the module change."
    fi
  } > "$body"
  git push -q -u origin "$branch"
  gh pr create --repo "$remote" --base "$base" --head "$branch" --title "$title" --body-file "$body"
  exit 0
fi

[ -z "$(git status --porcelain)" ] || { echo "error: the clone $PWD has uncommitted changes; clean it first" >&2; exit 1; }
git checkout -q -B "$branch" "origin/$base"
for file in $files; do
  if [ "$target" = infrastructure ]; then
    "$pin" terraform "$file" "$service" "$sha" "$version"
  elif grep -q "targetRevision: $service@" "$file"; then
    "$pin" argocd "$file" "$service" tag "$version"
  else
    "$pin" argocd "$file" "$service" sha "$sha" "$version"
  fi
done
git add -- $files
git commit --no-verify -q -m "$title"
git show --stat --format='%s' HEAD
echo "prepared branch $branch in $PWD. Edit it if needed, then run again with OPEN=1."
