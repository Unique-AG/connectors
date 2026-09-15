#!/usr/bin/env bash
# UN-23685: does POST /bulk-opportunity-stage-history actually move an opportunity's
# current stage, or does it only append history rows?
#
# A/B on two identical throwaway opportunities, both created in Prospect and both
# targeted at Invested (a `closed: true` stage):
#   X -> PATCH /opportunities/{id} relationships.stage
#   Y -> POST /bulk-opportunity-stage-history with effectiveDate = today
set -euo pipefail

cd "$(dirname "$0")/.."

INVESTOR=341644973
STAGE_PROSPECT=42478   # closed: false
STAGE_INVESTED=96016   # closed: true
TODAY=$(date +%Y-%m-%d)

create() { # $1 = name suffix
  uv run python agent-explore/write_probe.py POST /opportunities -l "ab-create-$1" -b "$(cat <<JSON
{"data":{"type":"opportunities","attributes":{
  "name":"ZZ AB Probe $1 UN-23685","currencyCode":"USD","isErisa":false},
 "relationships":{
  "investor":{"data":{"type":"contacts","id":"$INVESTOR"}},
  "stage":{"data":{"type":"opportunity-stages","id":"$STAGE_PROSPECT"}}}}}
JSON
)" 2>/dev/null | jq -r '.body.data.id'
}

report() { # $1 = id, $2 = label
  echo "--- $2 (opportunity $1) ---"
  uv run python agent-explore/explore.py "/opportunities/$1" \
    -p "include=stage" -p "bust=$2" 2>/dev/null \
    | jq '{
        currentStageId: .body.data.relationships.stage.data.id,
        currentStageName: [.body.included[]? | select(.type=="opportunity-stages") | .attributes.name][0],
        previousStage: .body.data.attributes.previousStage,
        isOpen: .body.data.attributes.isOpen,
        closedDate: .body.data.attributes.closedDate,
        dateEnteredCurrentStage: .body.data.attributes.dateEnteredCurrentStage,
        probability: .body.data.attributes.probability
      }'
  uv run python agent-explore/explore.py "/opportunities/$1/stageHistory" \
    -p "page[limit]=20" -p "bust=$2" 2>/dev/null \
    | jq '{status: .status, historyRows: [(.body.data // [])[] | {effectiveDate: .attributes.effectiveDate, stageId: .attributes.stage.resourceId}]}'
}

X=$(create X); echo "X = $X"
Y=$(create Y); echo "Y = $Y"
trap 'for i in "$X" "$Y"; do uv run python agent-explore/write_probe.py DELETE "/opportunities/$i" -l ab-delete >/dev/null 2>&1 || true; done; echo "### deleted $X $Y"' EXIT

report "$X" "00-X-baseline"
report "$Y" "00-Y-baseline"

echo
echo "########## X: PATCH relationships.stage -> Invested ##########"
uv run python agent-explore/write_probe.py PATCH "/opportunities/$X" -l ab-patch \
  -b "{\"data\":{\"type\":\"opportunities\",\"id\":\"$X\",\"relationships\":{\"stage\":{\"data\":{\"type\":\"opportunity-stages\",\"id\":\"$STAGE_INVESTED\"}}}}}" \
  2>/dev/null | jq '{status, error: .body.errors}'
report "$X" "01-X-after-patch"

echo
echo "########## Y: POST /bulk-opportunity-stage-history -> Invested (today) ##########"
uv run python agent-explore/write_probe.py POST /bulk-opportunity-stage-history -l ab-bulk -b "$(cat <<JSON
{"data":{"type":"bulk-opportunity-stage-history","attributes":{"records":[
  {"effectiveDate":"$TODAY",
   "opportunity":{"resourceId":"$Y","resourceType":"opportunities"},
   "stage":{"resourceId":"$STAGE_INVESTED","resourceType":"opportunity-stages"}}]}}}
JSON
)" 2>/dev/null | jq '{status, summary: .body.data.attributes.bulkLoadSummary}'
report "$Y" "01-Y-after-bulk"
