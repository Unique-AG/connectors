#!/usr/bin/env bash
# UN-23685 tools 5 and 6:
#   /contact-locations  create / patch / delete
#   /entity-relationships  employment create + endDate, and whether the reverse edge
#                          is a second record that must be end-dated too.
set -euo pipefail

cd "$(dirname "$0")/.."
CACHE=agent-explore/.probe-cache

TYPE_EMPLOYEE_OF=456439

getj() {
  local out newest
  out=$(uv run python agent-explore/explore.py "$@" 2>/dev/null)
  newest=$(ls -t "$CACHE" | head -1)
  rm -f "$CACHE/$newest"
  printf '%s' "$out"
}

w() { uv run python agent-explore/write_probe.py "$@" 2>/dev/null; }

PID=$(w POST /people -l le-person -b '{"data":{"type":"people","attributes":{"lastName":"LocEmpProbe","gender":"UNSPECIFIED","firstName":"Agent"}}}' | jq -r '.body.data.id')
OID=$(w POST /organizations -l le-org -b '{"data":{"type":"organizations","attributes":{"name":"ZZ LocEmp Org Probe"}}}' | jq -r '.body.data.id')
echo "person = $PID   org = $OID"
# Locations must be deleted BEFORE the party: deleting the party orphans them, and
# DELETE /contact-locations/{id} then 404s with PartyNotFoundException forever.
cleanup() {
  for loc in $(getj "/people/$PID" -p "include=contactLocations" | jq -r '.body.data.relationships.contactLocations.data[]?.id'); do
    w DELETE "/contact-locations/$loc" -l le-loc-cleanup >/dev/null || true
  done
  w DELETE "/people/$PID" -l le-person-del >/dev/null || true
  w DELETE "/organizations/$OID" -l le-org-del >/dev/null || true
  echo "### deleted person $PID org $OID and locations"
}
trap cleanup EXIT

echo
echo "############ TOOL 5: /contact-locations ############"

echo "### 5.0: create with contact.type = people (skill says plural resource name)"
w POST /contact-locations -l loc-people -b "{\"data\":{\"type\":\"contact-locations\",\"attributes\":{\"locationTitle\":\"Office\",\"address\":\"1 Original St\",\"city\":\"Zurich\",\"country\":\"CH\",\"phoneNumber\":\"+41 44 000 0000\"},\"relationships\":{\"contact\":{\"data\":{\"type\":\"people\",\"id\":\"$PID\"}}}}}" \
  | jq -c '{status, id: .body.data.id, err: (.body.errors // null)}'

echo "### 5.1: create with contact.type = contacts (swagger says contacts)"
LOC=$(w POST /contact-locations -l loc-contacts -b "{\"data\":{\"type\":\"contact-locations\",\"attributes\":{\"locationTitle\":\"Office\",\"address\":\"1 Original St\",\"city\":\"Zurich\",\"country\":\"CH\",\"phoneNumber\":\"+41 44 000 0000\"},\"relationships\":{\"contact\":{\"data\":{\"type\":\"contacts\",\"id\":\"$PID\"}}}}}" \
  | tee /tmp/loc.json | jq -r '.body.data.id')
jq -c '{status, id: .body.data.id, err: (.body.errors // null)}' /tmp/loc.json
echo "location = $LOC"

loc_snap() { getj "/contact-locations/$LOC" | jq -S '.body.data.attributes | del(.modifiedTimestamp, .createdTimestamp)'; }
loc_snap > /tmp/l_cur.json
echo "--- baseline ---"; cat /tmp/l_cur.json

echo "### 5.2: PATCH address only — do city / country / phone / locationTitle survive?"
w PATCH "/contact-locations/$LOC" -l loc-patch -b "{\"data\":{\"type\":\"contact-locations\",\"id\":\"$LOC\",\"attributes\":{\"address\":\"2 Patched Ave\"}}}" \
  | jq -c '{status, err: (.body.errors // null)}'
loc_snap > /tmp/l_new.json; echo "--- diff ---"; diff /tmp/l_cur.json /tmp/l_new.json || true; cp /tmp/l_new.json /tmp/l_cur.json

echo "### 5.3: locationTitle over maxLength (50 chars, documented limit 30)"
LONG=$(printf 'z%.0s' {1..50})
w PATCH "/contact-locations/$LOC" -l loc-maxlen -b "{\"data\":{\"type\":\"contact-locations\",\"id\":\"$LOC\",\"attributes\":{\"locationTitle\":\"$LONG\"}}}" \
  | jq -c '{status, err: (.body.errors // null)}'
loc_snap | jq '{locationTitleLength: (.locationTitle | length)}'

echo "### 5.4: is the location visible on the person's locations relationship?"
getj "/people/$PID" -p "include=locations" | jq -c '{locationIds: [.body.data.relationships.locations.data[]?.id]}'

echo "### 5.5: DELETE the location, then re-read"
w DELETE "/contact-locations/$LOC" -l loc-del | jq -c '{status}'
getj "/contact-locations/$LOC" | jq -c '{status, err: (.body.errors // null)}'

echo
echo "############ TOOL 6: employment via /entity-relationships ############"

echo "### 6.0: create 'is employee of' person -> org"
ER=$(w POST /entity-relationships -l er-create -b "{\"data\":{\"type\":\"entity-relationships\",\"attributes\":{\"sourceEntity\":{\"resourceId\":\"$PID\",\"resourceType\":\"people\"},\"destinationEntity\":{\"resourceId\":\"$OID\",\"resourceType\":\"organizations\"},\"startDate\":\"2020-01-01\"},\"relationships\":{\"entityRelationshipType\":{\"data\":{\"type\":\"entity-relationship-types\",\"id\":\"$TYPE_EMPLOYEE_OF\"}}}}}" \
  | tee /tmp/er.json | jq -r '.body.data.id')
jq -c '{status, id: .body.data.id, err: (.body.errors // null)}' /tmp/er.json
echo "entity-relationship = $ER"

echo "### 6.1: how many entity-relationships does the PERSON have? (one record or two?)"
getj "/people/$PID/entityRelationships" -p "page[limit]=10" | jq -c '{status, total: .body.meta.totalResourceCount, rows: [(.body.data // [])[] | {id, src: .attributes.sourceEntity.resourceId, dst: .attributes.destinationEntity.resourceId, start: .attributes.startDate, end: .attributes.endDate}]}'

echo "### 6.2: how many does the ORG have?"
getj "/organizations/$OID/entityRelationships" -p "page[limit]=10" | jq -c '{status, total: .body.meta.totalResourceCount, rows: [(.body.data // [])[] | {id, src: .attributes.sourceEntity.resourceId, dst: .attributes.destinationEntity.resourceId, start: .attributes.startDate, end: .attributes.endDate}]}'

echo "### 6.3: PATCH endDate on the created record only"
w PATCH "/entity-relationships/$ER" -l er-enddate -b "{\"data\":{\"type\":\"entity-relationships\",\"id\":\"$ER\",\"attributes\":{\"endDate\":\"2026-09-14\"}}}" \
  | jq -c '{status, endDate: .body.data.attributes.endDate, err: (.body.errors // null)}'

echo "### 6.4: person side after end-dating"
getj "/people/$PID/entityRelationships" -p "page[limit]=11" | jq -c '{rows: [(.body.data // [])[] | {id, start: .attributes.startDate, end: .attributes.endDate}]}'
echo "### 6.5: org side after end-dating"
getj "/organizations/$OID/entityRelationships" -p "page[limit]=11" | jq -c '{rows: [(.body.data // [])[] | {id, start: .attributes.startDate, end: .attributes.endDate}]}'

echo "### 6.6: can entityRelationshipType be PATCHed? (ticket says no)"
w PATCH "/entity-relationships/$ER" -l er-type -b "{\"data\":{\"type\":\"entity-relationships\",\"id\":\"$ER\",\"relationships\":{\"entityRelationshipType\":{\"data\":{\"type\":\"entity-relationship-types\",\"id\":\"459795\"}}}}}" \
  | jq -c '{status, err: (.body.errors // null)}'
getj "/entity-relationships/$ER" -p "include=entityRelationshipType" | jq -c '{typeId: .body.data.relationships.entityRelationshipType.data.id}'

w DELETE "/entity-relationships/$ER" -l er-del >/dev/null || true
