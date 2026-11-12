#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
home=${ROLLOUT_HOME:-$HOME/.config/release-rollout}
cluster=${1:?usage: checklist.sh <cluster> [env]}
env=${2:-}
[[ $cluster =~ ^[a-z0-9]+$ ]] || { echo "error: $cluster is not a cluster name" >&2; exit 2; }

cat "$root/checklists/default.md"
if [ -f "$home/checklists/$cluster.md" ]; then
  echo
  cat "$home/checklists/$cluster.md"
fi
if [ -f "$home/clusters.tsv" ]; then
  note=$(awk -F'\t' -v c="$cluster" -v e="$env" '$1 == c && (e == "" || $2 == e) && $4 != "-" { print $4 }' "$home/clusters.tsv" | sort -u | paste -sd ';' -)
  if [ -n "$note" ]; then
    echo
    echo "- The Deployment Overview comment for this cluster is: $note."
  fi
fi
