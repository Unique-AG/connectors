#!/usr/bin/env bash
# UN-23685 tool 5 (rerun): /contact-locations.
#
# First attempt was confounded: two creates reused locationTitle "Office" and the second
# failed on a uniqueness rule, not on the `contact` resourceType under test. Every create
# here uses a distinct title.
set -euo pipefail

cd "$(dirname "$0")/.."
CACHE=agent-explore/.probe-cache

getj() {
  local out newest
  out=$(uv run python agent-explore/explore.py "$@" 2>/dev/null)
  newest=$(ls -t "$CACHE" | head -1)
  rm -f "$CACHE/$newest"
  printf '%s' "$out"
}
w() { uv run python agent-explore/write_probe.py "$@" 2>/dev/null; }

mkloc() { # $1 = contact resourceType, $2 = locationTitle
  w POST /contact-locations -l "loc-$1" -b "{\"data\":{\"type\":\"contact-locations\",\"attributes\":{\"locationTitle\":\"$2\",\"address\":\"1 Original St\",\"city\":\"Zurich\",\"country\":\"CH\",\"phoneNumber\":\"+41 44 000 0000\",\"postalCode\":\"8001\"},\"relationships\":{\"contact\":{\"data\":{\"type\":\"$1\",\"id\":\"$PID\"}}}}}"
}

PID=$(w POST /people -l loc2-person -b '{"data":{"type":"people","attributes":{"lastName":"LocProbe2","gender":"UNSPECIFIED","firstName":"Agent"}}}' | jq -r '.body.data.id')
echo "person = $PID"

# Locations must be deleted BEFORE the party: deleting the party orphans them, and
# DELETE /contact-locations/{id} then 404s with PartyNotFoundException forever.
cleanup() {
  for loc in $(getj "/people/$PID" -p "include=contactLocations" | jq -r '.body.data.relationships.contactLocations.data[]?.id'); do
    w DELETE "/contact-locations/$loc" -l loc2-cleanup >/dev/null || true
  done
  w DELETE "/people/$PID" -l loc2-person-del >/dev/null || true
  echo "### deleted person $PID and its locations"
}
trap cleanup EXIT

echo "### which relationship names does a person expose for locations?"
getj "/people/$PID" | jq -c '{relNames: (.body.data.relationships | keys)}'

echo
echo "### A: contact.type = contacts  (title 'HQ-contacts')"
mkloc contacts "HQ-contacts" | jq -c '{status, id: .body.data.id, err: (.body.errors // null)}'

echo "### B: contact.type = people    (title 'HQ-people')"
LOC=$(mkloc people "HQ-people" | tee /tmp/l.json | jq -r '.body.data.id')
jq -c '{status, id: .body.data.id, err: (.body.errors // null)}' /tmp/l.json

echo "### C: duplicate title on the same party (uniqueness rule)"
mkloc people "HQ-people" | jq -c '{status, err: (.body.errors // null)}'

echo "### D: organizations as contact.type (should be rejected for a person id)"
mkloc organizations "HQ-orgtype" | jq -c '{status, err: (.body.errors // null)}'

echo
echo "location under test = $LOC"
loc_snap() { getj "/contact-locations/$LOC" | jq -S '.body.data.attributes | del(.modifiedTimestamp, .createdTimestamp)'; }
loc_snap > /tmp/lc.json; echo "--- baseline ---"; cat /tmp/lc.json

echo "### E: PATCH address only — does everything else survive?"
w PATCH "/contact-locations/$LOC" -l loc2-patch -b "{\"data\":{\"type\":\"contact-locations\",\"id\":\"$LOC\",\"attributes\":{\"address\":\"2 Patched Ave\"}}}" | jq -c '{status, err: (.body.errors // null)}'
loc_snap > /tmp/ln.json; echo "--- diff ---"; diff /tmp/lc.json /tmp/ln.json || true; cp /tmp/ln.json /tmp/lc.json

echo "### F: locationTitle over documented maxLength 30 (sending 50)"
LONG=$(printf 'z%.0s' {1..50})
w PATCH "/contact-locations/$LOC" -l loc2-maxlen -b "{\"data\":{\"type\":\"contact-locations\",\"id\":\"$LOC\",\"attributes\":{\"locationTitle\":\"$LONG\"}}}" | jq -c '{status, err: (.body.errors // null)}'
loc_snap | jq -c '{locationTitleLength: (.locationTitle | length)}'

echo "### G: which person relationship surfaces the locations?"
for rel in locations contactLocations; do
  echo -n "  include=$rel -> "
  getj "/people/$PID" -p "include=$rel" | jq -c "{status, ids: [.body.data.relationships.$rel.data[]?.id], err: (.body.errors // null)}"
done

echo "### H: DELETE then re-read"
w DELETE "/contact-locations/$LOC" -l loc2-del | jq -c '{status}'
getj "/contact-locations/$LOC" | jq -c '{status, err: (.body.errors // null)}'
