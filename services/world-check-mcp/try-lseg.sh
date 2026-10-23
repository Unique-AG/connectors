#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
set -a
source .env
set +a

curl -sS -u "$UPSTREAM_API_KEY:$UPSTREAM_API_SECRET" \
  -H 'Accept: application/json' \
  -d 'grant_type=client_credentials' \
  "${UPSTREAM_TOKEN_URL:-https://api.risk.lseg.com/auth/oauth2/v1/token}"
echo
