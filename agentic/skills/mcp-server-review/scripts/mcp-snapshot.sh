#!/usr/bin/env bash
# Read-only MCP server snapshot via the MCP Inspector CLI.
# Usage: mcp-snapshot.sh <out-dir> [inspector flags...] [stdio command...]
#   mcp-snapshot.sh /tmp/snap --transport http --server-url https://host/mcp --header "Authorization: Bearer $TOKEN"
#   mcp-snapshot.sh /tmp/snap node build/index.js
# Only calls initialize and the *list* methods. Never calls tools/call.
set -uo pipefail

OUT="${1:?usage: mcp-snapshot.sh <out-dir> [inspector target flags...]}"
shift
INSPECTOR="${MCP_INSPECTOR_PKG:-@modelcontextprotocol/inspector@2.15.0}"
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
mkdir -p "$OUT"
: >"$OUT/summary.txt"

run() {
  local name="$1" extra="$2"; shift 2
  pnpm --silent dlx "$INSPECTOR" --cli --stored-auth-only --method "$name" --format json $extra "$@" >"$OUT/${name//\//_}.json" 2>"$OUT/${name//\//_}.err"
  echo $?
}

INIT_EXIT=$(run initialize "" "$@")
if [ "$INIT_EXIT" != "0" ]; then
  echo "initialize failed (exit $INIT_EXIT): $(tail -n1 "$OUT/initialize.err")" >&2
  echo "Exit codes: 3=auth required, 4=unreachable, 11=rate limited. See references/inspector-cli.md" >&2
  exit "$INIT_EXIT"
fi
TOOLS_EXIT=$(run tools/list "--strict" "$@")
if { [ "$TOOLS_EXIT" != "0" ] && [ "$TOOLS_EXIT" != "6" ]; } || ! jq -e '.result.tools | arrays' "$OUT/tools_list.json" >/dev/null 2>&1; then
  echo "tools/list failed (exit $TOOLS_EXIT): $(tail -n1 "$OUT/tools_list.err")" >&2
  exit "${TOOLS_EXIT:-1}"
fi
RESOURCES_EXIT=$(run resources/list "" "$@")
TEMPLATES_EXIT=$(run resources/templates/list "" "$@")
PROMPTS_EXIT=$(run prompts/list "" "$@")

TOOLS="$OUT/tools_list.json"
jq -n \
  --slurpfile init "$OUT/initialize.json" \
  --slurpfile tools "$TOOLS" \
  --argjson strict_exit "$TOOLS_EXIT" '
  def depth: if type == "object" then ([.[] | depth] | max // 0) + 1
             elif type == "array" then ([.[] | depth] | max // 0) else 0 end;
  ($tools[0].result.tools // []) as $t
  | {
    server: ($init[0].result.serverInfo | del(.icons)),
    protocolVersion: $init[0].result.protocolVersion,
    capabilities: ($init[0].result.capabilities // {} | keys),
    has_instructions: (($init[0].result.instructions // "") != ""),
    tool_count: ($t | length),
    tool_definition_tokens_est: (($t | tojson | length) / 4 | floor),
    duplicate_names: ($t | group_by(.name) | map(select(length > 1) | .[0].name)),
    generic_names: ($t | map(.name) | map(select(test("^(search|get|list|create|update|delete|run|execute|query|fetch|send)(_[a-z]+)?$")))),
    missing_description: ($t | map(select((.description // "") == "") | .name)),
    short_description_lt_40: ($t | map(select((.description // "") | length | . > 0 and . < 40) | .name)),
    long_description_gt_1200: ($t | map(select((.description // "") | length > 1200) | .name)),
    missing_annotations: ($t | map(select(.annotations == null) | .name)),
    no_readOnlyHint_or_destructiveHint: ($t | map(select(.annotations != null and (.annotations.readOnlyHint == null and .annotations.destructiveHint == null)) | .name)),
    missing_outputSchema: ($t | map(select(.outputSchema == null) | .name)),
    params_without_description: ($t | map({tool: .name, params: [(.inputSchema.properties // {}) | to_entries[] | select((.value | type) == "object" and (.value.description // "") == "" and (.value.title // "") == "") | .key]} | select(.params | length > 0))),
    deep_schemas_gt_4: ($t | map({tool: .name, depth: (.inputSchema | depth)} | select(.depth > 4))),
    uses_anyOf_oneOf: ($t | map(select(.inputSchema | tojson | test("\"(anyOf|oneOf)\"")) | .name)),
    strict_exit: $strict_exit,
    strict_findings: ($tools[0].schemaFindings // {})
  }' >"$OUT/summary.json"

for entry in "resources/list:$RESOURCES_EXIT" "resources/templates/list:$TEMPLATES_EXIT" "prompts/list:$PROMPTS_EXIT"; do
  m="${entry%%:*}"
  f="$OUT/${m//\//_}.json"
  echo "$m exit=${entry##*:} count=$(jq '[.result[]? | arrays | length] | add // 0' "$f" 2>/dev/null)" >>"$OUT/summary.txt"
done
cat "$OUT/summary.json"
cat "$OUT/summary.txt" >&2
echo "raw outputs: $OUT/*.json" >&2
