#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
usage() {
  echo "usage: [NOTE=<text>] [TOOLS=<phrase>] slack.sh <service> <version> < targets.tsv" >&2
  echo "targets.tsv has one line per target, tab separated: cluster env from-version pr-url [action]" >&2
  exit 2
}
[ $# -eq 2 ] || usage
service=$1 to=$2
[[ $service =~ ^[a-z0-9][a-z0-9-]*$ && $to =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage

clients="" ours=""
while IFS=$'\t' read -r cluster env from pr action; do
  [ -n "$cluster" ] || continue
  rest=": $from → $to"
  if [ "$pr" != "-" ]; then rest="$rest, [#${pr##*/}]($pr)"; fi
  if [ -n "${action:-}" ] && [ "$action" != "-" ]; then rest="$rest. $action"; fi
  if [ "$cluster" = unique ] || [[ $env == uat* ]]; then
    ours="${ours}- \`$cluster/$env\`$rest"$'\n'
  else
    clients="${clients}- \`$cluster/$env\`$rest"$'\n'
  fi
done
[ -n "$clients$ours" ] || usage
targets=""
if [ -n "$clients" ]; then targets="*Clients*"$'\n'"$clients"$'\n'; fi
if [ -n "$ours" ]; then targets="${targets}*Unique*"$'\n'"$ours"$'\n'; fi

note="" tools=""
if [ -n "${NOTE:-}" ]; then note="*Please note*"$'\n'"$NOTE"$'\n\n'; fi
if [ -n "${TOOLS:-}" ]; then tools="*Tools:* $TOOLS"$'\n\n'; fi
export T_service=$service T_version=$to T_targets=${targets%$'\n\n'} T_note=$note T_tools=$tools
export T_release="https://github.com/Unique-AG/connectors/releases/tag/$service@$to"
perl -pe 's/\{\{(\w+)\}\}/$ENV{"T_$1"}/g' "$root/templates/slack-followup.md"
