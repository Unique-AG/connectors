#!/usr/bin/env bash
# Usage: record_all.sh login|discover|seed|record|check|report|all [--case ID] [--force] [--dry-run]
# login is the only step that needs a person: each test user signs in once.
# --dry-run sends no request and writes no state. It needs no SEED_UPNS.
# Otherwise set ENTRA_TENANT_ID, ENTRA_CLIENT_ID and SEED_UPNS (Mia, Anna, Tom).
set -euo pipefail

cd "$(dirname "$0")/../.."
exec .venv/bin/python -W ignore -m tests.e2e.recording.runbook "$@"
