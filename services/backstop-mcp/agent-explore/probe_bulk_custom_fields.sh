#!/usr/bin/env bash
# UN-23685 tool 3: POST /bulk-custom-field-values semantics.
#
# Definitions used (from the live catalog):
#   9910127  DROPDOWN     regular      "Read"                opts: Profund|Direct|Portal|No - Profund|No - Portal
#   9823191  SMALL_TEXT   regular      "Individual Contacted"
#   8746199  DROPDOWN     time-series  "CGM"                 opts: Yes|Yes - Melbourne|...|No Show
set -euo pipefail

cd "$(dirname "$0")/.."
CACHE=agent-explore/.probe-cache

DEF_DROPDOWN=9910127
DEF_TEXT=9823191
DEF_TS=8746199

getj() {
  local out newest
  out=$(uv run python agent-explore/explore.py "$@" 2>/dev/null)
  newest=$(ls -t "$CACHE" | head -1)
  rm -f "$CACHE/$newest"
  printf '%s' "$out"
}

bulk() { # $1 = label, $2 = records json array, $3 = resourceType
  uv run python agent-explore/write_probe.py POST /bulk-custom-field-values -l "cfv-$1" \
    -b "{\"data\":{\"type\":\"bulk-custom-field-values\",\"attributes\":{\"records\":$2,\"resource\":{\"resourceId\":\"$PID\",\"resourceType\":\"$3\"}}}}" \
    2>/dev/null | jq -c '{status, summary: .body.data.attributes.bulkLoadSummary, err: (.body.errors // null)}'
}

regular_values() {
  getj "/people/$PID" | jq -c '[.body.data.attributes.regularCustomFieldValues[]?
    | select(.definitionId == 9910127 or .definitionId == 9823191)
    | {definitionId, name, value}]'
}

ts_values() {
  getj "/people/$PID/timeSeriesCustomFieldValues" -p "page[limit]=20" \
    | jq -c '{status, rows: [(.body.data // [])[] | {definitionId: .attributes.definitionId, value: .attributes.value, effectiveDate: .attributes.effectiveDate}]}'
}

PID=$(uv run python agent-explore/write_probe.py POST /people -l cfv-person -b '{"data":{"type":"people","attributes":{"lastName":"CfvProbe","gender":"UNSPECIFIED","firstName":"Agent"}}}' 2>/dev/null | jq -r '.body.data.id')
echo "person = $PID"
trap 'uv run python agent-explore/write_probe.py DELETE "/people/$PID" -l cfv-delete >/dev/null 2>&1 || true; echo "### deleted person $PID"' EXIT

echo '### 0: which resourceType does the `resource` pointer want? try people, then contacts'
echo -n "  people:   "; bulk try-people   "[{\"definitionId\":$DEF_DROPDOWN,\"value\":\"Direct\"}]" people
echo -n "  contacts: "; bulk try-contacts "[{\"definitionId\":$DEF_DROPDOWN,\"value\":\"Direct\"}]" contacts
echo "  regular values now: $(regular_values)"

echo "### 1: regular SMALL_TEXT write"
bulk text "[{\"definitionId\":$DEF_TEXT,\"value\":\"probe text value\"}]" people
echo "  regular values now: $(regular_values)"

echo "### 2: regular DROPDOWN with an INVALID option (does Backstop validate?)"
bulk bad-option "[{\"definitionId\":$DEF_DROPDOWN,\"value\":\"NotARealOption\"}]" people
echo "  regular values now: $(regular_values)"

echo "### 3: repeat write to the same regular definition (overwrite or duplicate?)"
bulk overwrite "[{\"definitionId\":$DEF_DROPDOWN,\"value\":\"Portal\"}]" people
echo "  regular values now: $(regular_values)"

echo "### 4: time-series definition WITHOUT effectiveDate"
bulk ts-no-date "[{\"definitionId\":$DEF_TS,\"value\":\"Yes\"}]" people
echo "  ts values now: $(ts_values)"

echo "### 5: time-series definition WITH effectiveDate"
bulk ts-with-date "[{\"definitionId\":$DEF_TS,\"value\":\"Yes\",\"effectiveDate\":\"2026-03-01\"}]" people
echo "  ts values now: $(ts_values)"

echo "### 6: regular definition WITH an effectiveDate (ignored or error?)"
bulk regular-with-date "[{\"definitionId\":$DEF_DROPDOWN,\"value\":\"Profund\",\"effectiveDate\":\"2026-03-01\"}]" people
echo "  regular values now: $(regular_values)"
echo "  ts values now: $(ts_values)"

echo "### 7: unknown definitionId (per-record error shape)"
bulk bad-def "[{\"definitionId\":999999999,\"value\":\"x\"},{\"definitionId\":$DEF_TEXT,\"value\":\"still written\"}]" people
echo "  regular values now: $(regular_values)"
