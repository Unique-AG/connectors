#!/usr/bin/env bash
# Usage and settings: tests/e2e/recording/README.md, section "Record chosen cases again".
set -euo pipefail

cd "$(dirname "$0")/../.."
settings="${DOGFOOD_ENV:-$HOME/.config/dogfood/env}"
if [ -f "$settings" ]; then
  set -a
  . "$settings"
  set +a
fi
: "${ENTRA_TENANT_ID:?set ENTRA_TENANT_ID or write it in $settings}"
: "${ENTRA_CLIENT_ID:?set ENTRA_CLIENT_ID or write it in $settings}"
: "${SEED_UPNS:?set SEED_UPNS (Mia, Anna, Tom) or write it in $settings}"
export ENTRA_TENANT_ID ENTRA_CLIENT_ID SEED_UPNS

usage="usage: rerecord.sh login | rerecord.sh plan CASE [CASE ...] | rerecord.sh run CASE [CASE ...]"
mode="${1:?$usage}"
shift
cases=()
for one in "$@"; do cases+=(--case "$one"); done
case "$mode" in
  login)
    exec scripts/dogfood/record_all.sh login
    ;;
  plan)
    [ "$#" -gt 0 ] || { echo "plan needs at least one case id" >&2; exit 2; }
    exec scripts/dogfood/record_all.sh report --dry-run --force "${cases[@]}"
    ;;
  run)
    [ "$#" -gt 0 ] || { echo "run needs at least one case id" >&2; exit 2; }
    status=0
    scripts/dogfood/record_all.sh record --force "${cases[@]}" || status=$?
    scripts/dogfood/record_all.sh report || true
    [ "$status" -eq 0 ] || { echo "recording failed with exit $status; see .record-all/" >&2; exit "$status"; }

    domain="${SEED_UPNS%%,*}"
    domain="${domain#*@}"
    RECORD_LINT_IDENTITIES="$ENTRA_TENANT_ID,$domain,$SEED_UPNS" \
      .venv/bin/python -W ignore -m tests.e2e.recording.lint --require-identities
    .venv/bin/python -m pytest tests/e2e tests/tools tests/test_use_cases.py -q -W ignore
    ;;
  *)
    echo "$usage" >&2
    exit 2
    ;;
esac
