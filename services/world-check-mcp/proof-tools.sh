#!/usr/bin/env bash
set -u

cd "$(dirname "$0")"
url="http://127.0.0.1:8000/mcp"

run() {
  local shown="$1"
  shift
  printf '\n$ %s\n' "$shown"
  npx --yes @modelcontextprotocol/inspector --cli "$url" --transport http "$@"
  echo
}

run "inspector --method initialize" \
  --method initialize

run "inspector --method tools/list" \
  --method tools/list

run "inspector --method tools/call --tool-name get_api_info" \
  --method tools/call --tool-name get_api_info --tool-args-json '{}'

run "inspector --method tools/call --tool-name list_groups" \
  --method tools/call --tool-name list_groups --tool-args-json '{}'

run "inspector --method tools/call --tool-name get_reference_data --tool-arg kind=api_info" \
  --method tools/call --tool-name get_reference_data --tool-args-json '{"kind":"api_info"}'

run "inspector --method tools/call --tool-name get_group_settings --tool-arg group_id=example-id-00000000000001" \
  --method tools/call --tool-name get_group_settings --tool-args-json '{"group_id":"example-id-00000000000001"}'

run "inspector --method tools/call --tool-name get_case --tool-arg case=missing-case" \
  --method tools/call --tool-name get_case --tool-args-json '{"case":"missing-case"}'
