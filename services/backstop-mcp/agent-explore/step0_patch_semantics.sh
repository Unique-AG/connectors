#!/usr/bin/env bash
# UN-23685 Step 0: does a Backstop PATCH merge or replace?
# Creates a throwaway opportunity on the sandbox, PATCHes one field at a time,
# and diffs the full record after each write. Deletes the record at the end.
set -euo pipefail

cd "$(dirname "$0")/.."
OUT=/tmp/step0
rm -rf "$OUT" && mkdir -p "$OUT"

INVESTOR=341644973
PRODUCT_A=1292283
PRODUCT_B=1292323
STAGE_PROJECT=42480
USER_A=2967455
USER_B=3566561

snap() { # $1 = opportunity id, $2 = label
  uv run python agent-explore/explore.py "/opportunities/$1" -p "bust=$2" 2>/dev/null \
    | jq -S '{
        attributes: (.body.data.attributes | del(.modifiedTimestamp)),
        relationships: (.body.data.relationships
          | with_entries(select(.value.data != null))
          | map_values(.data))
      }' > "$OUT/$2.json"
}

diffsnap() { # $1 = before label, $2 = after label
  echo "--- diff $1 -> $2 ---"
  diff "$OUT/$1.json" "$OUT/$2.json" || true
}

echo "### create"
ID=$(uv run python agent-explore/write_probe.py POST /opportunities -l step0-create -b "$(cat <<JSON
{"data":{"type":"opportunities","attributes":{
  "name":"ZZ Step0 Probe UN-23685","description":"original description",
  "currencyCode":"USD","isErisa":false,
  "requestedAmount":"1000000","allocatedAmount":"500000","probability":"0.42",
  "expectedInvestmentDate":"2027-01-01","otherId":"STEP0-OTHER","aliases":"step0-alias"},
 "relationships":{
  "investor":{"data":{"type":"contacts","id":"$INVESTOR"}},
  "product":{"data":{"type":"products","id":"$PRODUCT_A"}},
  "stage":{"data":{"type":"opportunity-stages","id":"$STAGE_PROJECT"}},
  "ccedUsers":{"data":[{"type":"system-users","id":"$USER_A"},{"type":"system-users","id":"$USER_B"}]}}}}
JSON
)" 2>/dev/null | jq -r '.body.data.id')
echo "created opportunity $ID"
trap 'echo "### delete $ID"; uv run python agent-explore/write_probe.py DELETE "/opportunities/$ID" -l step0-delete >/dev/null 2>&1 || true' EXIT

snap "$ID" 00-baseline
echo "### baseline"
cat "$OUT/00-baseline.json"

echo "### test 1: PATCH one attribute (description) only"
uv run python agent-explore/write_probe.py PATCH "/opportunities/$ID" -l step0-attr \
  -b "{\"data\":{\"type\":\"opportunities\",\"id\":\"$ID\",\"attributes\":{\"description\":\"patched description\"}}}" \
  >/dev/null 2>&1
snap "$ID" 01-after-attr
diffsnap 00-baseline 01-after-attr

echo "### test 2: PATCH one to-one relationship (product) only"
uv run python agent-explore/write_probe.py PATCH "/opportunities/$ID" -l step0-toone \
  -b "{\"data\":{\"type\":\"opportunities\",\"id\":\"$ID\",\"relationships\":{\"product\":{\"data\":{\"type\":\"products\",\"id\":\"$PRODUCT_B\"}}}}}" \
  >/dev/null 2>&1
snap "$ID" 02-after-toone
diffsnap 01-after-attr 02-after-toone

echo "### test 3: PATCH one attribute, to-many (ccedUsers) omitted"
uv run python agent-explore/write_probe.py PATCH "/opportunities/$ID" -l step0-omit-tomany \
  -b "{\"data\":{\"type\":\"opportunities\",\"id\":\"$ID\",\"attributes\":{\"aliases\":\"step0-alias-2\"}}}" \
  >/dev/null 2>&1
snap "$ID" 03-after-omit-tomany
diffsnap 02-after-toone 03-after-omit-tomany

echo "### test 4: PATCH to-many explicitly to empty array"
uv run python agent-explore/write_probe.py PATCH "/opportunities/$ID" -l step0-clear-tomany \
  -b "{\"data\":{\"type\":\"opportunities\",\"id\":\"$ID\",\"relationships\":{\"ccedUsers\":{\"data\":[]}}}}" \
  >/dev/null 2>&1
snap "$ID" 04-after-clear-tomany
diffsnap 03-after-omit-tomany 04-after-clear-tomany

echo "### test 5: PATCH attribute explicitly to null"
uv run python agent-explore/write_probe.py PATCH "/opportunities/$ID" -l step0-null-attr \
  -b "{\"data\":{\"type\":\"opportunities\",\"id\":\"$ID\",\"attributes\":{\"otherId\":null}}}" \
  >/dev/null 2>&1
snap "$ID" 05-after-null-attr
diffsnap 04-after-clear-tomany 05-after-null-attr
