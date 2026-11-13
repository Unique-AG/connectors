#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
only_service=${1:-}
only_cluster=${2:-}
repo=$("$here/clone.sh" monorepo)

latest=$(git ls-remote --tags https://github.com/Unique-AG/connectors.git 'refs/tags/*@*' |
  sed -nE 's#.*refs/tags/([a-z0-9-]+)@([0-9]+\.[0-9]+\.[0-9]+)$#\1 \2#p' |
  sort -k1,1 -k2,2V | awk '{ v[$1] = $2 } END { for (s in v) print s, v[s] }')

services=$(gh api -H 'Accept: application/vnd.github.raw+json' repos/Unique-AG/connectors/contents/.release-please-manifest.json --jq . | jq -r 'keys[] | select(startswith("services/")) | ltrimstr("services/")')

printf 'cluster\tenv\tapp\tservice\tshipped\tavailable\tstate\tautosync\n'
git -C "$repo" grep -nE 'x-[a-z0-9-]+-version' -- gitops-resources/argocd/clusters |
  while IFS=: read -r file _ line; do
    [[ $file =~ clusters/([^/]+)/([^/]+)/application-specs/[^/]+/([^/]+)/ ]] || continue
    cluster=${BASH_REMATCH[1]}
    env=${BASH_REMATCH[2]}
    app=${BASH_REMATCH[3]}
    [[ $line =~ x-([a-z0-9-]+)-version ]] || continue
    service=${BASH_REMATCH[1]}
    grep -qxF "$service" <<< "$services" || continue
    [ -z "$only_service" ] || [ "$only_service" = "$service" ] || continue
    [ -z "$only_cluster" ] || [ "$only_cluster" = "$cluster" ] || continue
    available=$(awk -v s="$service" '$1 == s { print $2 }' <<< "$latest")
    pin="$service@([0-9]+\\.[0-9]+\\.[0-9]+[0-9A-Za-z.-]*)"
    shipped=dev
    if [[ $line =~ $pin ]]; then shipped=${BASH_REMATCH[1]}; fi
    if [ "$shipped" = dev ]; then
      state=dev
    elif [ -z "$available" ]; then
      state=unreleased
    elif [ "$shipped" = "$available" ]; then
      state=current
    elif [ "$(printf '%s\n%s\n' "$shipped" "$available" | sort -V | head -1)" = "$shipped" ]; then
      state=behind
    else
      state=ahead
    fi
    autosync=$(sed -nE 's/^ *autoSync: *([a-z]+).*/\1/p' "$repo/$file" | head -1)
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$cluster" "$env" "$app" "$service" "$shipped" "${available:--}" "$state" "${autosync:-unset}"
  done | sort -u -t "$(printf '\t')" -k4,4 -k1,1 -k2,2 -k3,3
