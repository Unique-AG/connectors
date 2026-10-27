# Cassette recorder

The recorder runs a scenario's chain through the real app and the real tools against Microsoft
Graph. It then scrubs the answers, lints them, replays them through the runner, and writes a
cassette in the runner's format. Raw answers stay in memory. Only the scrubbed files are written.

| File | Job |
| --- | --- |
| `record.py` | Command line and `record()`: guard, `/me` check, capture at the httpx transport, scrub, lint, replay check, write |
| `guard.py` | Decides on each tool call and each request before it is sent (plan v3 R4) |
| `scrub.py` | Projection, corpus allowlist, keyed id mapper, binary by hash (plan v3 R2) |
| `lint.py` | Second line behind the scrub; also the CI lint (plan v3 R3) |
| `drift.py` | Records again in memory and compares each file byte for byte |
| `stand_in.py` | An offline Graph with seed data and foreign data, for the tests |
| `recorded.calls.yaml` | The recording variant of each recorded scenario |

## What the scrub keeps

- A response key that `SCHEMA` in `scrub.py` does not name is dropped.
- Free text (subject, preview, names, summaries) stays only if it is text of the seed corpus
  (`scripts/dogfood/seed/seed.py corpus`). Other text becomes `synthetic text NN`.
- A persona address becomes `mia@example.test`, `anna@example.test` or `tom@example.test`. Any
  other address becomes `user-NN@example.test`.
- An id keeps its length, its punctuation and its known prefix (`AAMkAG`, `b!`, `01`). Its letters
  and digits come from a keyed hash, so a second record gives the same ids. A GUID becomes
  `00000000-xxxx-4xxx-8xxx-xxxxxxxxxxxx`.
- A binary body must have the SHA-256 of a file that the seed generator made. Any other binary
  stops the run and nothing is written.
- Response headers: only `content-type`, `location`, `retry-after` and `preference-applied`.
  URL parameters: an allowlist; `tempauth`, `sig` and all others are dropped.

The recorder prints the counts of each replacement. It refuses to write when the variant's
`expect` reads a field that the scrub replaced or dropped.

## The guard

- Tools: an allowlist of read tools and of four write tools (`outlook_move_mail`,
  `outlook_mark_mail`, `outlook_draft_mail`, `outlook_create_event` without attendees, rooms or
  online meeting). A write needs `--allow-writes`.
- Paths: `/v1.0/me/...`, the recording user's own `/v1.0/users/<id or UPN>/...`, the user's own
  drive, and `/v1.0/search/query` for `sharepoint_search_files` only. Another host is allowed only
  for the redirect that Graph answered, and only without a token.
- A write may only change an item that the same run read as seed data (category or name
  `seed-v1`), or move into a well-known folder. After a write gets 429 or 5xx, no other write is
  sent.
- Addresses: any `@`, also full-width or percent-encoded, must be an address that `getaddresses`
  parses, with an IDNA domain equal to the domain of `SEED_UPNS`.
- A cap of 40 requests per run (`--max-requests`, at most 100).
- The checks use `if`, not `assert`, so `python -O` keeps them.

## Before a live run

1. The seed is applied for all three testers, Mia last, on the day you record
   (`scripts/dogfood/seed/README.md`). The variant expectations use the "received yesterday" mail
   of the seed. On a later day, run the seed `cleanup` and `apply` again.
2. `ENTRA_TENANT_ID` and `ENTRA_CLIENT_ID` are set for `get_token.py`. The app has User.Read
   consented (`GET /me` and `GET /organization` need it).
3. `SEED_UPNS` lists the three testers, Mia first. Mia is the recording user.

## Commands

Run from `services/office-365-mcp`.

```sh
export SEED_UPNS="<Mia UPN>,<Anna UPN>,<Tom UPN>"   # the same value the seed uses
MIA="${SEED_UPNS%%,*}"

# 1. Offline: tests and the dry run. No token, no request.
.venv/bin/python -m pytest tests/e2e/recording -q -p no:cacheprovider
.venv/bin/python -m tests.e2e.recording.record uc-02-01 uc-01-06 --target graph --dry-run
.venv/bin/python -m tests.e2e.recording.record uc-05-16 --target graph --dry-run --allow-writes

# 2. The token. get_token.py writes the sign-in prompt to stderr and the token to stdout only.
export GRAPH_TOKEN="$(.venv/bin/python scripts/dogfood/get_token.py "$MIA")"

# 3. Record. uc-05-16 moves three seed mails to Archive.
.venv/bin/python -m tests.e2e.recording.record uc-02-01 uc-01-06 --target graph --link
.venv/bin/python -m tests.e2e.recording.record uc-05-16 --target graph --allow-writes --link

# 4. The second record (B6): reads only. It must print "no drift".
.venv/bin/python -m tests.e2e.recording.drift uc-02-01 uc-01-06 --target graph
unset GRAPH_TOKEN

# 5. The lint with the identities: tenant id, tenant name, domain, the three UPNs, user ids.
export RECORD_LINT_IDENTITIES="<tenant id>,<tenant name>,<tenant domain>,$SEED_UPNS"
.venv/bin/python -m tests.e2e.recording.lint --require-identities
```

Exit codes of `record`: 0 written; 1 written, but the variant's `expect` does not hold (the
recorder shows the values; update `recorded.calls.yaml` and replay); 2 refused, nothing written.

The files go to `tests/e2e/cassettes/rec-<id>.json`, `rec-<id>.meta.yaml` and
`tests/e2e/fixtures/rec-<id>.NN.*`. To land them, add `--link` to the command. It copies the
scenario's block from `recorded.calls.yaml` into its sidecar entry as `variants: recorded:`, and
only after a recording whose `expect` holds. It prints the number of runs. Set `_MINIMUM_EXECUTABLE`
to that number, run `pnpm exec biome check --write services/office-365-mcp/tests/e2e` from the
repository root (CI fails on the unformatted files that the recorder writes), and run
`uv run pytest tests/e2e tests/test_use_cases.py`. The tenant owner
reads the first cassette diff before any push.

To record uc-05-16 again, run the seed `cleanup` and `apply` as Mia first. The first run moved
the three newest seed mails.

Offline, `--target stand-in` uses `stand_in.py` and writes to a temporary folder unless you give
`--out`.

## What only the live run shows

- That the real answers fit the projection: a key that a tool reads but `SCHEMA` drops shows as
  `dropped` in "tool output changed by the scrub". Add the key to `SCHEMA` and record again.
- That Exchange returns the seed text unchanged (subjects, previews, HTML bodies) and that
  OneDrive returns the seed docx with the same SHA-256. SharePoint can write properties into an
  Office file, and then the recorder refuses the binary.
- That `get_token.py`'s scopes are enough: `GET /organization` needs User.Read, and the search
  of uc-01-06 can need Files.Read.All or Sites.Read.All.
- The real paging, nextLink form, 302 location and id formats.
- That the foreign data in Mia's mailbox and OneDrive does not come first in a result that a
  variant expectation reads. If it does, the recorder refuses and names the selector.
