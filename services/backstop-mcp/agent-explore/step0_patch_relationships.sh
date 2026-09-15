#!/usr/bin/env bash
# UN-23685 Step 0 (part 2): PATCH merge-vs-replace for relationships, plus the
# semantics of POST /bulk-opportunity-stage-history.
#
# Relationship linkage only appears under `relationships.<name>.data` when the GET
# asks for `include=`, so every snapshot here side-loads the relationships under test.
set -euo pipefail

cd "$(dirname "$0")/.."
OUT=/tmp/step0rel
rm -rf "$OUT" && mkdir -p "$OUT"

INVESTOR=341644973
PRODUCT_A=1292283
PRODUCT_B=1292323
STAGE_PROJECT=42480
STAGE_IDD=42482
STAGE_EXECUTION=85444
USER_A=2967455
USER_B=3566561

INCLUDE="product,ccedUsers,stage,investor"

snap() { # $1 = opportunity id, $2 = label
  uv run python agent-explore/explore.py "/opportunities/$1" \
    -p "include=$INCLUDE" -p "bust=$2" 2>/dev/null \
    | jq -S '{
        stageId: .body.data.relationships.stage.data.id,
        productId: .body.data.relationships.product.data.id,
        investorId: .body.data.relationships.investor.data.id,
        ccedUserIds: [.body.data.relationships.ccedUsers.data[]?.id] | sort,
        previousStage: .body.data.attributes.previousStage,
        description: .body.data.attributes.description
      }' > "$OUT/$2.json"
}

diffsnap() { echo "--- diff $1 -> $2 ---"; diff "$OUT/$1.json" "$OUT/$2.json" || true; }

echo "### create"
ID=$(uv run python agent-explore/write_probe.py POST /opportunities -l rel-create -b "$(cat <<JSON
{"data":{"type":"opportunities","attributes":{
  "name":"ZZ Step0 Rel Probe UN-23685","description":"original",
  "currencyCode":"USD","isErisa":false},
 "relationships":{
  "investor":{"data":{"type":"contacts","id":"$INVESTOR"}},
  "product":{"data":{"type":"products","id":"$PRODUCT_A"}},
  "stage":{"data":{"type":"opportunity-stages","id":"$STAGE_PROJECT"}},
  "ccedUsers":{"data":[{"type":"system-users","id":"$USER_A"},{"type":"system-users","id":"$USER_B"}]}}}}
JSON
)" 2>/dev/null | jq -r '.body.data.id')
echo "created opportunity $ID"
trap 'echo "### delete $ID"; uv run python agent-explore/write_probe.py DELETE "/opportunities/$ID" -l rel-delete >/dev/null 2>&1 || true' EXIT

snap "$ID" 00-baseline
echo "### baseline"; cat "$OUT/00-baseline.json"

echo "### test A: PATCH to-one (product) only — do stage / ccedUsers / investor survive?"
uv run python agent-explore/write_probe.py PATCH "/opportunities/$ID" -l rel-toone \
  -b "{\"data\":{\"type\":\"opportunities\",\"id\":\"$ID\",\"relationships\":{\"product\":{\"data\":{\"type\":\"products\",\"id\":\"$PRODUCT_B\"}}}}}" >/dev/null 2>&1
snap "$ID" 01-after-toone
diffsnap 00-baseline 01-after-toone

echo "### test B: PATCH one attribute only — do all relationships survive?"
uv run python agent-explore/write_probe.py PATCH "/opportunities/$ID" -l rel-attr \
  -b "{\"data\":{\"type\":\"opportunities\",\"id\":\"$ID\",\"attributes\":{\"description\":\"patched\"}}}" >/dev/null 2>&1
snap "$ID" 02-after-attr
diffsnap 01-after-toone 02-after-attr

echo "### test C: PATCH to-many (ccedUsers) explicitly to empty array"
uv run python agent-explore/write_probe.py PATCH "/opportunities/$ID" -l rel-clear \
  -b "{\"data\":{\"type\":\"opportunities\",\"id\":\"$ID\",\"relationships\":{\"ccedUsers\":{\"data\":[]}}}}" >/dev/null 2>&1
snap "$ID" 03-after-clear
diffsnap 02-after-attr 03-after-clear

echo
echo "########## POST /bulk-opportunity-stage-history ##########"
TODAY=$(date +%Y-%m-%d)

echo "### test D: bulk stage history, effectiveDate = TODAY ($TODAY) -> Execution"
uv run python agent-explore/write_probe.py POST /bulk-opportunity-stage-history -l bulk-today -b "$(cat <<JSON
{"data":{"type":"bulk-opportunity-stage-history","attributes":{"records":[
  {"effectiveDate":"$TODAY",
   "opportunity":{"resourceId":"$ID","resourceType":"opportunities"},
   "stage":{"resourceId":"$STAGE_EXECUTION","resourceType":"opportunity-stages"}}]}}}
JSON
)" 2>/dev/null | jq '{status, body}'
snap "$ID" 04-after-bulk-today
diffsnap 03-after-clear 04-after-bulk-today

echo "### test E: bulk stage history, effectiveDate BACKDATED (2026-02-01) -> IDD"
uv run python agent-explore/write_probe.py POST /bulk-opportunity-stage-history -l bulk-backdated -b "$(cat <<JSON
{"data":{"type":"bulk-opportunity-stage-history","attributes":{"records":[
  {"effectiveDate":"2026-02-01",
   "opportunity":{"resourceId":"$ID","resourceType":"opportunities"},
   "stage":{"resourceId":"$STAGE_IDD","resourceType":"opportunity-stages"}}]}}}
JSON
)" 2>/dev/null | jq '{status, body}'
snap "$ID" 05-after-bulk-backdated
diffsnap 04-after-bulk-today 05-after-bulk-backdated

echo "### test F: bulk with one good and one bogus opportunity id (partial failure shape)"
uv run python agent-explore/write_probe.py POST /bulk-opportunity-stage-history -l bulk-partial -b "$(cat <<JSON
{"data":{"type":"bulk-opportunity-stage-history","attributes":{"records":[
  {"effectiveDate":"$TODAY",
   "opportunity":{"resourceId":"$ID","resourceType":"opportunities"},
   "stage":{"resourceId":"$STAGE_PROJECT","resourceType":"opportunity-stages"}},
  {"effectiveDate":"$TODAY",
   "opportunity":{"resourceId":"999999999","resourceType":"opportunities"},
   "stage":{"resourceId":"$STAGE_PROJECT","resourceType":"opportunity-stages"}}]}}}
JSON
)" 2>/dev/null | jq '{status, body}'
snap "$ID" 06-after-bulk-partial
diffsnap 05-after-bulk-backdated 06-after-bulk-partial

echo "### final stage history"
uv run python agent-explore/explore.py "/opportunities/$ID/stageHistory" -p "page[limit]=20" 2>/dev/null \
  | jq '{total: .body.meta.totalResourceCount, rows: [.body.data[] | {effectiveDate: .attributes.effectiveDate, stageId: .attributes.stage.resourceId}]}'
