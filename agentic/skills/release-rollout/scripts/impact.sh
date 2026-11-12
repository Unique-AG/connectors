#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
usage() { echo "usage: impact.sh <service> <from-version> <to-version> <cluster> <env>" >&2; exit 2; }
[ $# -eq 5 ] || usage
service=$1 from=$2 to=$3 cluster=$4 env=$5
[[ $service =~ ^[a-z0-9][a-z0-9-]*$ ]] || usage
[[ $from =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $to =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage
[[ $cluster =~ ^[a-z0-9]+$ && $env =~ ^[a-z0-9]+$ ]] || usage

cd "$(git rev-parse --show-toplevel)"
git fetch -q --tags origin
a="$service@$from"
b="$service@$to"
for tag in "$a" "$b"; do
  git rev-parse -q --verify "refs/tags/$tag" > /dev/null || { echo "error: the tag $tag does not exist" >&2; exit 1; }
done

chart=services/$service/deploy/helm-charts/$service
shared=$(git show "$b:services/$service/deploy/Dockerfile" 2> /dev/null | grep -oE '^COPY packages/[A-Za-z0-9_-]+' | cut -d' ' -f2 || true)
none() { grep -E "$@" || echo "(none)"; }
changed() { git diff -U0 "$a" "$b" -- "$@"; }
schema() { git show "$1:$chart/values.schema.json"; }
paths='def p($x): (.properties // {}) | to_entries[] | ($x + [.key]) as $k | ($k | join(".")), (.value | p($k)); p([])'
required='def r($x): ((.required // [])[] | ($x + [.] | join("."))), ((.properties // {}) | to_entries[] | . as $e | ($e.value | r($x + [$e.key]))); r([])'

printf '# %s %s -> %s on %s/%s\n' "$service" "$from" "$to" "$cluster" "$env"
printf '== terraform: changed files\n'
git diff --name-only "$a" "$b" -- "services/$service/deploy/terraform" ':!*.lock.hcl' | none .
printf '== terraform: variables and outputs\n'
changed "services/$service/deploy/terraform" ':!*.lock.hcl' | none '^[+-][[:space:]]*(variable|output) "'
printf '== terraform: scopes and roles\n'
changed "services/$service/deploy/terraform" ':!*.lock.hcl' | none -i '^[+-].*(scope|app_role|role_id|permission|\.All)'
printf '== infrastructure pins (* marks this cluster)\n'
infra=$("$here/clone.sh" infrastructure)
git -C "$infra" grep -n "x-$service-version" -- providers |
  sed -E 's/^([^:]+):[0-9]+:.*(x-[a-z0-9-]+-version.*)$/\1 \2/' |
  awk -v c="/$cluster/" '{ print (index($1, c) ? "* " : "  ") $0 }' | none .

printf '== chart: keys added\n'
added=$(comm -13 <(schema "$a" | jq -r "$paths" | sort) <(schema "$b" | jq -r "$paths" | sort))
printf '%s\n' "$added" | none .
printf '== chart: keys removed\n'
removed=$(comm -23 <(schema "$a" | jq -r "$paths" | sort) <(schema "$b" | jq -r "$paths" | sort))
printf '%s\n' "$removed" | none .
printf '== chart: keys now required\n'
needed=$(comm -13 <(schema "$a" | jq -r "$required" | sort) <(schema "$b" | jq -r "$required" | sort))
printf '%s\n' "$needed" | none .
printf '== chart: default changes in values.yaml\n'
changed "$chart/values.yaml" | none '^[+-][^+-]'

printf '== settings and environment reads\n'
files=$(git diff --name-only "$a" "$b" -- "services/$service" $shared | grep -E '/(config|settings)[^/]*\.(py|ts)$|\.env\.example$' | grep -Ev '/tests?/' || true)
if [ -n "$files" ]; then changed $files | none '^[+-][^+-]'; else echo "(none)"; fi
changed "services/$service" $shared ':!*/tests/*' ':!*.md' | none '^\+[^+].*(os\.environ|os\.getenv|process\.env|BaseSettings|validation_alias|env_prefix)'

repo=$("$here/clone.sh" monorepo)
app=$(git -C "$repo" grep -l "x-$service-version" -- "gitops-resources/argocd/clusters/$cluster/$env")
[ "$(wc -l <<< "$app")" -eq 1 ] && [ -n "$app" ] || { echo "error: expected one $service app spec in $cluster/$env" >&2; exit 1; }
overlay="$repo/$(dirname "$app")/values.yaml"
overlay_keys=$(awk '
  /^[[:space:]]*(#|$)/ || /^[[:space:]]*- / { next }
  { match($0, /^ */); i = RLENGTH; s = substr($0, i + 1) }
  s !~ /^[A-Za-z0-9_."-]+:( |$)/ { next }
  { sub(/:.*/, "", s); while (n > 0 && st[n] >= i) n--; n++; st[n] = i; k[n] = s; p = k[1]; for (j = 2; j <= n; j++) p = p "." k[j]; print p }
' "$overlay" | sort -u)
printf '== overlay %s\n' "${overlay#"$repo"/}"
for key in $needed; do
  grep -qxF "$key" <<< "$overlay_keys" || echo "required key not in overlay: $key"
done
for key in $removed; do
  if grep -qxF "$key" <<< "$overlay_keys"; then echo "removed key still in overlay: $key"; fi
done
unset_count=0
for key in $added; do
  grep -qxF "$key" <<< "$overlay_keys" || unset_count=$((unset_count + 1))
done
echo "added keys not set in the overlay, so they use the chart default: $unset_count"
