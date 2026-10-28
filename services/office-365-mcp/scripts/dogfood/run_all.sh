#!/usr/bin/env bash
# Usage: run_all.sh verify|apply|cleanup-dry|cleanup [index ...]   (indexes default to 1 2 3)
# SEED_UPNS lists the three test users in the order Mia, Anna, Tom. Index N signs in as the Nth address.
# Each user signs in once (first run only); later runs use the cached refresh token.
# Needs ENTRA_TENANT_ID and ENTRA_CLIENT_ID.
set -euo pipefail

command="${1:?usage: run_all.sh verify|apply|cleanup-dry|cleanup [index ...]}"
shift
indexes=("${@:-1 2 3}")
read -r -a indexes <<<"${indexes[*]}"
cd "$(dirname "$0")/../.."
python="$PWD/.venv/bin/python"
: "${ENTRA_TENANT_ID:?set ENTRA_TENANT_ID}" "${ENTRA_CLIENT_ID:?set ENTRA_CLIENT_ID}"
: "${SEED_UPNS:?set SEED_UPNS to the three test UPNs: Mia, Anna, Tom}"
export SEED_UPNS
IFS=',' read -r -a upns <<<"$SEED_UPNS"

for index in "${indexes[@]}"; do
  upn="${upns[$((index - 1))]}"
  echo "== persona $index = $upn ($command) =="
  GRAPH_TOKEN="$("$python" scripts/dogfood/get_token.py "$upn")"
  export GRAPH_TOKEN
  case "$command" in
    verify) "$python" -W ignore scripts/dogfood/seed/verify.py --as "$index" ;;
    apply) "$python" -W ignore scripts/dogfood/seed/seed.py apply --as "$index" ;;
    cleanup-dry) "$python" -W ignore scripts/dogfood/seed/seed.py cleanup --as "$index" --dry-run ;;
    cleanup) "$python" -W ignore scripts/dogfood/seed/seed.py cleanup --as "$index" ;;
    *) echo "unknown command: $command" >&2; exit 2 ;;
  esac
  unset GRAPH_TOKEN
done
