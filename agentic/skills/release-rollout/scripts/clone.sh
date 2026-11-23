#!/usr/bin/env bash
set -euo pipefail

case ${1:-} in
  monorepo) repo=monorepo branch=master path=gitops-resources/argocd ;;
  infrastructure) repo=infrastructure branch=main path=providers ;;
  *) echo "usage: clone.sh monorepo|infrastructure" >&2; exit 2 ;;
esac

dir="${TMPDIR:-/tmp}/bump-service/$repo"
[ -d "$dir/.git" ] || git clone -q --filter=blob:none --sparse --depth 1 --branch "$branch" "https://github.com/Unique-AG/$repo.git" "$dir"
git -C "$dir" sparse-checkout set "$path"
git -C "$dir" fetch -q --depth 1 origin "$branch"
git -C "$dir" checkout -q --detach "origin/$branch"
echo "$dir"
