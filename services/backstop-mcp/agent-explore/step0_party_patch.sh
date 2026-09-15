#!/usr/bin/env bash
# UN-23685 Step 0 (part 3): PATCH merge-vs-replace on /people and /organizations,
# including the to-many `categories` relationship, explicit-null clears, maxLength
# handling, and whether a required attribute can be nulled.
#
# `/people/{id}` rejects unknown query params (400 InvalidParameterException), so the
# usual cache-busting dummy param is not available. Instead each GET drops its own
# `.probe-cache` entry so the next identical read re-fetches.
set -euo pipefail

cd "$(dirname "$0")/.."
CACHE=agent-explore/.probe-cache

CAT_A=9615     # GVS
CAT_B=12467    # Equity Replacement prospect
CAT_C=12469    # Web Portal

getj() { # $@ = explore.py args
  local out newest
  out=$(uv run python agent-explore/explore.py "$@" 2>/dev/null)
  newest=$(ls -t "$CACHE" | head -1)
  rm -f "$CACHE/$newest"
  printf '%s' "$out"
}

person_snap() { # $1 = id
  getj "/people/$1" -p "include=categories" | jq -S '{
    attributes: (.body.data.attributes
      | del(.modifiedTimestamp, .createdTimestamp, .regularCustomFieldValues)),
    categoryIds: ([.body.data.relationships.categories.data[]?.id] | sort)
  }'
}

echo "############ PERSON ############"
PID=$(uv run python agent-explore/write_probe.py POST /people -l party-person-create -b "$(cat <<JSON
{"data":{"type":"people","attributes":{
  "lastName":"Step0Probe","gender":"UNSPECIFIED","firstName":"Agent",
  "email":"step0.probe@example.invalid","email2":"step0.two@example.invalid",
  "email3":"step0.three@example.invalid",
  "mobilePhone":"+1 555 0100","jobTitle":"Original Title","department":"Original Dept",
  "otherId":"STEP0-PERSON","nickName":"Probe"},
 "relationships":{"categories":{"data":[
   {"type":"contact-categories","id":"$CAT_A"},
   {"type":"contact-categories","id":"$CAT_B"}]}}}}
JSON
)" 2>/dev/null | jq -r '.body.data.id')
echo "person = $PID"
trap 'uv run python agent-explore/write_probe.py DELETE "/people/$PID" -l party-person-delete >/dev/null 2>&1 || true;
      [ -n "${OID:-}" ] && uv run python agent-explore/write_probe.py DELETE "/organizations/$OID" -l party-org-delete >/dev/null 2>&1 || true;
      echo "### deleted person $PID org ${OID:-none}"' EXIT

person_snap "$PID" > /tmp/p00.json
echo "--- baseline ---"; cat /tmp/p00.json

ppatch() { # $1 = label, $2 = json body fragment for data
  uv run python agent-explore/write_probe.py PATCH "/people/$PID" -l "party-$1" \
    -b "{\"data\":{\"type\":\"people\",\"id\":\"$PID\",$2}}" 2>/dev/null \
    | jq -c '{status, err: (.body.errors // empty)}'
}

pdiff() { echo "--- diff: $1 ---"; person_snap "$PID" > /tmp/p_new.json; diff /tmp/p_cur.json /tmp/p_new.json || true; cp /tmp/p_new.json /tmp/p_cur.json; }
cp /tmp/p00.json /tmp/p_cur.json

echo "### A: PATCH email only"
ppatch a-email '"attributes":{"email":"step0.patched@example.invalid"}'
pdiff "A (expect only email changed; categories intact)"

echo "### B: PATCH jobTitle only, categories omitted"
ppatch b-jobtitle '"attributes":{"jobTitle":"Patched Title"}'
pdiff "B (expect only jobTitle changed; categories intact)"

echo "### C: PATCH categories to a single different category (replace vs append?)"
ppatch c-categories "\"relationships\":{\"categories\":{\"data\":[{\"type\":\"contact-categories\",\"id\":\"$CAT_C\"}]}}"
pdiff "C (expect categoryIds == [$CAT_C] if replace, 3 ids if append)"

echo "### D: PATCH categories to empty array"
ppatch d-categories-clear '"relationships":{"categories":{"data":[]}}'
pdiff "D (expect categoryIds == [])"

echo "### E: PATCH department explicitly to null"
ppatch e-null '"attributes":{"department":null}'
pdiff "E (expect department cleared)"

echo "### F: PATCH jobTitle over maxLength (200 chars, documented limit 140)"
LONG=$(printf 'x%.0s' {1..200})
ppatch f-maxlen "\"attributes\":{\"jobTitle\":\"$LONG\"}"
person_snap "$PID" | jq '{jobTitleLength: (.attributes.jobTitle | length)}'
pdiff "F (did Backstop reject, truncate, or store 200?)"

echo "### G: PATCH required attribute lastName to null"
ppatch g-null-required '"attributes":{"lastName":null}'
pdiff "G (does Backstop reject nulling a required field?)"

echo
echo "############ ORGANIZATION ############"
OID=$(uv run python agent-explore/write_probe.py POST /organizations -l party-org-create -b '{"data":{"type":"organizations","attributes":{"name":"ZZ Step0 Org Probe","email":"org.step0@example.invalid","website":"https://example.invalid","legalName":"ZZ Step0 Legal Name","otherId":"STEP0-ORG"}}}' 2>/dev/null | jq -r '.body.data.id')
echo "org = $OID"

org_snap() {
  getj "/organizations/$OID" | jq -S '{attributes: (.body.data.attributes | del(.modifiedTimestamp, .createdTimestamp, .regularCustomFieldValues))}'
}
org_snap > /tmp/o_cur.json
echo "--- baseline ---"; cat /tmp/o_cur.json

echo "### H: PATCH org email only — does required name survive?"
uv run python agent-explore/write_probe.py PATCH "/organizations/$OID" -l party-org-email \
  -b "{\"data\":{\"type\":\"organizations\",\"id\":\"$OID\",\"attributes\":{\"email\":\"org.patched@example.invalid\"}}}" 2>/dev/null \
  | jq -c '{status, err: (.body.errors // empty)}'
org_snap > /tmp/o_new.json; echo "--- diff H ---"; diff /tmp/o_cur.json /tmp/o_new.json || true; cp /tmp/o_new.json /tmp/o_cur.json

echo "### I: PATCH org name over maxLength (80 chars, documented limit 50)"
LONGN=$(printf 'y%.0s' {1..80})
uv run python agent-explore/write_probe.py PATCH "/organizations/$OID" -l party-org-maxlen \
  -b "{\"data\":{\"type\":\"organizations\",\"id\":\"$OID\",\"attributes\":{\"name\":\"$LONGN\"}}}" 2>/dev/null \
  | jq -c '{status, err: (.body.errors // empty)}'
org_snap | jq '{nameLength: (.attributes.name | length)}'
