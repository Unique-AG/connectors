#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
home=${ROLLOUT_HOME:-$HOME/.config/release-rollout}
usage() {
  echo "usage: [NOTE=<text>] slack.sh <service> <version> < targets.tsv" >&2
  echo "targets.tsv has one line per target, tab separated: cluster env from-version pr-url [action]" >&2
  exit 2
}
[ $# -eq 2 ] || usage
service=$1 to=$2
[[ $service =~ ^[a-z0-9][a-z0-9-]*$ && $to =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage

targets=""
while IFS=$'\t' read -r cluster env from pr action; do
  [ -n "$cluster" ] || continue
  client=""
  if [ -f "$home/clusters.tsv" ]; then
    client=$(awk -F'\t' -v c="$cluster" -v e="$env" '$1 == c && $2 == e { print $3 }' "$home/clusters.tsv")
  fi
  line="• *${client:-$cluster}* \`$cluster/$env\`: $from → $to, <$pr|#${pr##*/}>"
  if [ -n "${action:-}" ] && [ "$action" != "-" ]; then line="$line. $action"; fi
  targets="$targets$line"$'\n'
done
[ -n "$targets" ] || usage

note=""
if [ -n "${NOTE:-}" ]; then note="*Please note*"$'\n'"$NOTE"$'\n\n'; fi
export T_service=$service T_version=$to T_targets=${targets%$'\n'} T_note=$note
export T_release="https://github.com/Unique-AG/connectors/releases/tag/$service@$to"
perl -pe 's/\{\{(\w+)\}\}/$ENV{"T_$1"}/g' "$root/templates/slack-followup.md"
