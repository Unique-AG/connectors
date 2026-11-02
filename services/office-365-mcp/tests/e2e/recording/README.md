# Fixture recorder

The recorder runs a scenario's chain through the real app and the real tools against Microsoft
Graph. It then scrubs the answers, lints them, replays them through the runner, and writes a
fixture in the runner's format. Raw answers stay in memory. Only the scrubbed files are written.

| File | Job |
| --- | --- |
| `record.py` | Command line and `record()`: guard, `/me` check, capture at the httpx transport, scrub, lint, replay check, write |
| `guard.py` | Decides on each tool call and each request before it is sent (plan v3 R4) |
| `scrub.py` | Projection, corpus allowlist, keyed id mapper, binary by hash (plan v3 R2) |
| `lint.py` | Second line behind the scrub; also the CI lint (plan v3 R3) |
| `drift.py` | Records again in memory and compares each file byte for byte |
| `stand_in.py` | An offline Graph with seed data and foreign data, for the tests |
| `recorded.calls.yaml` | The recording variant of each recorded scenario |
| `cases/*.yaml` | One tool case per tool and scenario of use. A case records one tool |
| `families/*.py` | Plain data per tool family: allowlists, schema keys, needs. `load()` merges them |
| `runbook.py` | Plans, records, checks and reports all cases (`scripts/dogfood/record_all.sh`) |

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
- An attachment keeps its `contentBytes` only when the SHA-256 of the decoded bytes is in the seed
  corpus manifest. Other bytes become `synthetic text NN`, and the lint refuses them.
- The HTML of a OneNote page (`GET /me/onenote/pages/{id}/content`) keeps its tags. A text node or
  a text attribute stays only if it is corpus text. An id goes through the mapper. An address in
  `src`, `data-fullres-src` or `data` keeps a Graph host only, and any other address becomes
  `synthetic text NN`. A comment is dropped. The lint checks the same rules in `bodies/*.html`.
- When the lint or the replay check refuses a case, the scrubbed candidate goes to
  `.record-all/refused/<case>/` (mode 700, ignored by git). A lint finding names the JSON path of
  the leaf and the class of the match, never the text. A later good record deletes the folder.
- Response headers: only `content-type`, `location`, `retry-after` and `preference-applied`.
  URL parameters: an allowlist; `tempauth`, `sig` and all others are dropped.

The recorder prints the counts of each replacement. It refuses to write when the variant's
`expect` reads a field that the scrub replaced or dropped.

## The guard

- Tools: the read tools and the write tools of the family modules. A write needs
  `--allow-writes`. A write tool that invites people or rooms is refused.
- Paths: `/v1.0/me/...`, the recording user's own `/v1.0/users/<id or UPN>/...`, the user's own
  drive, the `PREFIXES` of the families (GET only), and the POST globs of `READ_POSTS` and the GET
  globs of `READ_GETS` for the named read tool only. A write path must match a glob of its tool, one path segment for each
  `*`. Another host is allowed only
  for the redirect that Graph answered, and only without a token.
- A write may only change an item that the same run read as seed data (category or name
  `seed-v1`), or created itself (a 201 answer to a write), or move into a well-known folder. A
  value under a `DESTINATIONS` key follows the same rule. The key is the full path in the JSON body,
  so `id` names the top-level `id` only, and the `id` of an attachment is no destination. A value under a `FORBIDDEN` key is
  refused. A write glob with no `*` outside `/v1.0/me/` needs a `seed-v1 case-` name in the body.
  An event of the default calendar passes when the run read the event as seed data or created it.
  After any 429 or 5xx answer, or a send that raises, no write is sent.
- A write of a tool in `CREATED_ONLY` must name an item that the same run created. The number is
  the position of the `*` that holds that item. A chat is created by `POST /v1.0/chats`, and its
  topic must hold `seed-v1 case-`.
- A body that binds a person (`users('<id>')`) must name a test user, by id or by address. The
  preflight reads the ids of the other test users (`GET /v1.0/users/<UPN>?$select=id`) only when a
  case uses `persona:<key>.id`. A membership of a test user in a chat is known after a listing.
- Addresses: any `@`, also full-width or percent-encoded, must be an address that `getaddresses`
  parses. The address, with its IDNA domain, must be one of `SEED_UPNS`. A send of a draft is
  refused when an answer of the run showed a recipient that is not one of `SEED_UPNS`.
- The preflight reads `/me/drive` for the drive id. A token with no Files scope gets no drive id,
  and the run goes on without the drive.
- A cap of 40 requests per run (`--max-requests`, at most 100).
- The checks use `if`, not `assert`, so `python -O` keeps them.

## Tool cases

A case file `cases/<family>.yaml` maps `<tool>-<slug>` to an entry. The last step of the chain is
the tool under test. The earlier steps set up or find what it needs. The chain uses the words of
the sidecars: `tool`, `args`, `bind`, `expect`.

```yaml
outlook_move_mail-archive:
  persona: 1          # position in SEED_UPNS, default 1
  destructive: true   # consumes a seed item; the runbook reseeds the `reseed` phases after it
  reseed: [mail]
  external: false     # the effect reaches other personas
  needs: []           # keys of NEEDS in a family module; a missing need blocks the case
  cap: 40             # optional request cap, 1..100
  scopes: []          # Graph permission names added to the narrow token, such as Group.Read.All
  gap: 0              # seconds to wait before the next case, 0..600
  chain:
    - {tool: outlook_list_mail, args: {category: seed-v1, limit: 1}}
    - tool: outlook_move_mail
      args: {destination: archive}
      bind: {message_refs: "$prev.messages[*].uri"}
```

A bind can read an attribute of markup that an earlier step returned: `$prev.html~img[src]` is
the `src` of the first `<img>`. A bind can also be a list or an object whose leaves are binds, for
the person objects of the chat tools.

A case never holds an address or an id of a test user. It writes `persona:<key>` for the address,
`persona:<key>.id` for the Entra object id and `persona:<key>.name` for the display name of the
corpus. `<key>` is `mia`, `anna` or `tom`. The recorder puts the real value into the live run and
the synthetic value into the replay check. An unknown placeholder stops the run.

A tool can declare fewer scopes than Graph needs for one call. Name the missing permissions in
`scopes`. `get_token.py --scopes-for TOOL --scopes NAME` adds them to the token of that case, and
`login` asks for them of all cases, so the admin consents once.

The fixture is `rec-tool-<id>`. A case that creates what it changes needs no reseed: name the item
`seed-v1 case-<id>`, and `seed.py cleanup --cases --as N` deletes it. `--link` does not apply to a
case. Record one case with
`python -m tests.e2e.recording.record <id> --target stand-in --allow-writes`.

## Families

`families/<family>.py` exports plain data. Each name is optional: `READ_TOOLS`, `READ_POSTS`,
`READ_GETS`, `WRITE_TOOLS`, `EXTERNAL`, `SCHEMA`, `PREFIXES`, `DESTINATIONS`, `FORBIDDEN`, `CREATED_ONLY`, `THREAD_ID`,
`BODIES`, `LEAKS`, `NEEDS`, `UNRECORDED`, `PROBES` and `GAP_SECONDS`. `GAP_SECONDS` is the wait
after a case of the family, unless the case has its own `gap`. `UNRECORDED` maps a tool with no case to the
reason. A test needs every tool to have a case or an `UNRECORDED` entry, and the report lists them.
`load()` merges them and raises `ValueError` when a tool is claimed twice, a glob is too broad, or a
`SCHEMA` key changes the Kind of a core key. A family
cannot change the core rules of the guard.

The report lists a tool of `UNRECORDED` under "Simulated or human steps" when its reason starts with
the text of a `NEEDS` key.

The seed side has the same shape: `scripts/dogfood/seed/families/<family>.py` exports `PHASES`,
`steps(ctx, owner, phases)` and `sweep(graph, owner)`.

## The runbook

```sh
scripts/dogfood/record_all.sh login|discover|seed|record|check|report|all [--case ID] [--force] [--dry-run]
```

`login` is the only step that needs a person. `--dry-run` sends no request and writes no state.
State goes to `.record-all/` (`discover.json`, `results.json`, `report.md`). The report has
three lists (recorded, refused, blocked) and a list of simulated or human steps. A run is
resumable: a case whose fixture exists is skipped unless you give `--force`. A skipped case
replaces an earlier blocked or refused result. `check` also runs the seed tests.

- A case that runs longer than 600 seconds is refused with the note `timed out after N seconds`.
  The run goes on with the next case.
- A throttled case runs again once, but only when it has no write step. The refusal names a
  `retry-after`, and it is 0 when Graph sent no header. The runbook waits for the longer of
  `retry-after` and 60 seconds, and never more than 300 seconds.
- A case that binds a value from a search tool (a tool name with `search` or `find`) can fail when
  the search index has no hit yet. The runbook runs it again up to 3 times, 60 seconds apart. It
  does this only when the refusal is that bind message and no write step comes before the failing
  bind.
- A case with `gap: N` makes the runbook wait N seconds before the next case that it runs.

The report lists the tools of `UNRECORDED` under "Not recorded", each with its reason.

## Before a live run

1. The seed is applied for all three testers, Mia last, on the day you record
   (`scripts/dogfood/seed/README.md`). The variant expectations use the "received yesterday" mail
   of the seed. On a later day, run the seed `cleanup` and `apply` again.
2. `ENTRA_TENANT_ID` and `ENTRA_CLIENT_ID` are set for `get_token.py`. The app has User.Read
   consented (`GET /me` and `GET /organization` need it).
   The seed team (`record_all.sh seed`) needs Team.Create. After a new scope, run
   `record_all.sh login` again, because a cached sign-in does not hold the new scope.
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

The files go to `tests/e2e/fixtures/rec-<id>.json`, `rec-<id>.meta.yaml` and
`tests/e2e/bodies/rec-<id>.NN.*`. To land them, add `--link` to the command. It copies the
scenario's block from `recorded.calls.yaml` into its sidecar entry as `variants: recorded:`, and
only after a recording whose `expect` holds. It prints the number of runs. Set `_MINIMUM_EXECUTABLE`
to that number, run `pnpm exec biome check --write services/office-365-mcp/tests/e2e` from the
repository root (CI fails on the unformatted files that the recorder writes), and run
`uv run pytest tests/e2e tests/test_use_cases.py`. The tenant owner
reads the first fixture diff before any push.

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
