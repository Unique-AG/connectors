# Polixis MCP

Looks up organizations and people in Polixis corporate data: search, profiles with sanctions and
PEP flags, related parties, ultimate beneficial owners and top-down ownership, linked companies,
sanctions exposure, the path between two parties, the flagged parties near one and court
decisions.

## Tools

| Tool | Polixis endpoint | Pages |
|---|---|---|
| `search_entities` | `POST /search/api` | Polixis' own pages |
| `get_entity_profiles` | `POST /api/completion/{id}`, once per pid, up to 10 at once | |
| `get_related_parties` | `POST /api/corporate/byPublisher?page=&size=40` | Polixis's page of each source, merged per party, then pages by tokens from the cache |
| `get_ultimate_beneficial_owners` | `GET /api/graph/ubo/{id}` | Ours, one row per owner |
| `get_top_down_ownership` | `GET /api/graph/topdown/{id}` | Ours, one row per holding |
| `find_linked_companies` | `POST /api/graph/smart`, with `/api/graph/subgraph` for `scope: all` | Ours, over the companies |
| `find_connections` | `POST /api/graph/path` (undocumented) | |
| `find_flagged_parties` | `POST /api/graph/subgraph` and `/api/graph/smart` | Ours, over the parties |
| `get_sanctions_exposure` | `GET /api/sanction/{id}` (undocumented) | Ours, over the parties |
| `find_court_decisions` | `GET /api/judicial/{id}` (undocumented) | Ours, over the decisions |
| `get_court_decision` | `GET /api/judicial/{id}` (undocumented) | Ours, over the text |
| `resolve_permanent_id` | `GET /api/graph/pid/{pid}` | Served from the spec |

Every tool only reads, and every tool but `resolve_permanent_id` is our own, mapped in
`contexts/`: Polixis' graph and ownership responses run to a megabyte for a large company, far
more than an agent's context holds. So the tools answer a question rather than pass a response
on: the ownership tools add up every chain to an entity into one row and rank the rows by
effective share, the graph tools return the companies, paths or flagged parties the question
asks for, and every list comes ranked with its totals and flagged entries up front, so the first
page usually settles it and the agent pages on only when the question needs the rest.

### Pages sized by tokens

An agent's context is finite, and its client caps what one tool call may return: Claude Code
warns past 10,000 tokens and cuts a result off at 25,000 by default, wherever that falls. So
the tools aim for three things:

- **One call for a typical client.** A page holds as many rows as fit in about 8,000 tokens
  (`PAGE_TOKENS` in `contexts/pages.py`), not a fixed count, so a company with a few dozen
  related parties or owners comes back whole, with `next_cursor` null.
- **No page past the cap.** A page is the rows' 8,000 tokens plus its totals and flagged
  summary; the largest measured is 9,589. A decision's text comes in parts of the same size.
- **An early stop for a large group.** Every list is ranked, and its totals and flagged
  entries come first, so a question about the top of the list or about whether something is
  there ends on page 1. A question whose answer is the list itself needs every page: no
  design shrinks that, short of returning fewer fields per row.

`page_size` caps the rows on a page for an agent that wants only the first few.
`search_entities` is paged by Polixis, which counts rows, so its default page size is set to
come to about the same 8,000 tokens. `get_related_parties` asks Polixis for 40 parties of each
source, which is one response of up to a few hundred parties for a large group, merges a party
several sources report into one, and pages that by tokens from the cache; past the last party it
asks Polixis for its next page.

Measured over the live Polixis responses saved in November 2026: a large group whose one-hop
graph has 527 parties, a sanctioned PEP, and a second person for the paths and court decisions,
taking the median where there is more than one sample. Tokens are UTF-8 bytes of JSON divided
by 4, which also roughly holds for Cyrillic; no tokenizer service saw the data. "Without
pagination" is what the tool would return in one response; a ≈ marks a figure scaled from the
rows measured to the whole list. The figures for `search_entities`, `find_flagged_parties` and
`find_linked_companies` were measured before their rows stopped repeating names, so they are
upper bounds.

| Tool | Tokens without pagination | Tokens per page | Questions |
|---|---:|---:|---|
| `get_ultimate_beneficial_owners` | 8,165 (66 owners) | 8,165, one page | **Page 1:** who holds 25% or more, who is at the end of each chain, which owners are flagged, the sanctioned owners' shares for the 50% rule. **Every page:** the full owner table, which for most companies is this one page anyway. |
| `get_top_down_ownership` | 100,648 (488 holdings) | about 8,500, 12 pages | **Page 1:** the controlled subsidiaries, and whether the group holds anything flagged or state-owned, since the flagged list covers the whole tree. **Every page:** mapping the whole group or listing every minority stake. The answer is the list. |
| `find_linked_companies` | 38,049 (455 companies) | about 8,600, 5 pages | **Page 1:** the companies tied directly, the flagged ones and the totals. **Every page:** every company tied through people, for a full report. |
| `find_flagged_parties` | 57,475 (282 flagged, at radius 2; the default is 1) | about 8,600, 7 pages at radius 2 | **Page 1:** whether any sanctioned, PEP or state-owned party is near, the most severe ones with their paths, and how many there are. **Every page:** a list of every flagged party with its path. |
| `get_sanctions_exposure` | 18,501 (85 parties) | about 8,600, 3 pages | **Page 1:** whether the entity is listed itself, the nearest sanctioned parties and how many there are. **Every page:** every sanctioned party with its path, for a report. |
| `find_court_decisions` | 2,044 (20 decisions) | 2,044, one page | **Page 1:** every decision with its court, year and snippets, which often show what it is about. |
| `get_court_decision` | 4,662 for the median decision; about 31,000 for the longest, of 62,000 Cyrillic characters | 8,000 at most, 1 to 4 parts | **First part:** usually the whole decision. **Every part:** reading a long decision in full; check the snippets of `find_court_decisions` first. |
| `get_related_parties` | ≈106,000 (587 parties) | about 8,800 (a large group's first Polixis page: 30 parties of 22 sources over 6 pages) | Parties with a current relation come first, then those most sources report. **One page:** a small company's parties, or a large one's narrowed by `categories`. For flagged parties among them, `find_flagged_parties` with `radius` 1 answers in one call. **Every page:** screening every party of a large company, 15 pages for this one. |
| `search_entities` | ≈809,000 (1,010 hits for one common name) | about 8,000 for the default 10 | **Page 1:** the closest matches, which Polixis ranks first. Narrow a common name by country, date or type rather than page through it. **Every page:** never needed in practice; say how many hits there were. |
| `find_connections` | 358 | one result | **One call:** the shortest path Polixis finds. |
| `get_entity_profiles` | 760 to 1,192 per pid, about 12,000 for 10 | not paged | **One call:** up to 10 profiles. Ten large organizations with the key sections pass the 10,000 warning but stay well under the 25,000 cap; the `sanctions` and `positions` sections make each profile larger, so ask for fewer pids with them. |

### What each tool combines

| Tool | What it combines, and what else it does |
|---|---|
| `find_flagged_parties` | Joins the smart graph, which names the parties, with the subgraph, which holds every relation; searches the network for every party with a sanctions, PEP or state-ownership marker (282 of 526) and gives the path to each, the most severe risk first (sanctioned, PEP, restricted, REP, state-owned) and the nearest first within each; counts them by marker on every page, so a 0 settles a question such as "is any of them state-owned?" in one call; says when Polixis cut the graph short |
| `find_linked_companies` | Finds the companies tied to the entity directly or through people in between, which no Polixis endpoint answers, with the chain of people and links behind each, the flagged ones counted by marker. The default two hops reads a larger graph than the one-hop sample measured |
| `get_top_down_ownership` | One row per holding (488 entities, 97 of them reached by more than one chain), with the share carried summed over every chain, ranked by it, and its 213 flagged holdings counted by marker, with the first 25 up front, the sanctioned first |
| `get_court_decision` | One decision's text, in parts of about 8,000 tokens, read from the cache `find_court_decisions` filled: Polixis has no route for one decision |
| `find_court_decisions` | The decisions without their texts, those naming the entity first and the newest next, with the snippets cleared of Polixis's `<em>` highlighting |
| `get_sanctions_exposure` | Each sanctioned party's lists, status, programmes and listing date, with listing dates read from the four forms the lists write them in, and the parties nearest first |
| `get_related_parties` | Sends `category` and `page`, without which Polixis answers a 500; merges the groups Polixis returns per source, which it keeps even with `page`, into one entry per party with every source's relations, and counts each source's parties in `relations_by_source`; flattens its flags, share text, dates and countries; keeps a party without a pid, with `pid` null, when it has a name. At Polixis's maximum page of 200 its response is about 135,000 tokens |
| `get_ultimate_beneficial_owners` | One row per owner with its share summed over every distinct chain, ranked by it, so a 25% question stops at the first share below it once `total_share_unknown` shows no unread owner whose share may be higher; the end of each chain marked; the flagged owners counted by marker, with the first 25 up front, the sanctioned first |
| `search_entities` | Turns `1978-02` into Polixis's `19780200`, leaves out unset filters, which Polixis would read as null, and keeps ten names of a hit, its typed name records first and no spelling twice, and three addresses, of up to 60 and 20 |
| `find_connections` | Orders the path's links from the first entity, which Polixis lists in no order, folds the repeated composite nodes, and names every party on it with its flags |
| `get_entity_profiles` | Not size, which its field names add to: up to 10 pids in one call, Polixis's requests sent in parallel, sections named in plain words in place of Polixis's field names, and a pid Polixis rejects reported on that profile instead of failing the others |

Every one of them also gets, from the shared client and context code:

- every date field in one form, `YYYY`, `YYYY-MM` or `YYYY-MM-DD`, whether Polixis sent a date
  object, Unix seconds or sanctions-list text (a profile's raw sanction `details` stay as
  Polixis wrote them);
- an id Polixis does not know reported as an error, where Polixis answers a 200 with an error
  body;
- the response cache below, so paging, a second tool on the same entity, or the same search or
  profile asked again does not ask Polixis again;
- at most four requests to Polixis at once per process, and no request at all for a while once
  Polixis says the quota is spent, with an error that says so.
- the alerts Polixis marks `hidden` left out, as its documentation says to ignore them.

A field the MCP computes rather than takes from Polixis, such as an effective share, a path,
a hop count or a risk marker, says so: its description starts with "Computed by this MCP" and
says how, and the server instructions tell the agent to say so when it reports one and to
explain how from that description. Every other field is Polixis's, renamed or reformatted.
Keep to that for a new field. The flags and alerts are described as Polixis's documentation
defines them (Annexes 1 and 4 of its Corporate and Graph API PDF). The `REP` flag is not
among them, though the live graph sends it on many parties, so it is described as undefined and
still counted as a risk marker.

The tools marked undocumented call routes Polixis answers but leaves out of its spec. Whether
it supports them is an open question to Polixis, so their descriptions tell the agent the
answers may change.

A tool that can return more than one page answers with a `next_cursor`, and the agent passes it
back alone as `cursor`: it carries every argument of the first call, base64-encoded. Where
Polixis pages a list itself, the cursor asks it for the next page. Where it returns everything
at once (the ownership trees, the graphs, the sanctions exposure, the court decisions and the
path between two parties), the next page, or another tool on the same entity, reads the response
from the cache instead of asking Polixis again.

Every tool of our own reuses Polixis's answers from Postgres (`persistence/response_cache.py`)
for `RESPONSE_CACHE_TTL_SECONDS`, 15 minutes by default, so the same request within that time
spares the API key's quota. The answers are licensed data about real people, which Polixis
updates in real time, so the TTL cannot exceed an hour. The TTL limits reuse, not storage: the
server deletes the expired entries when it starts and once per TTL after, so an answer normally
leaves Postgres within twice the TTL, later when a cleanup fails.
`RESPONSE_CACHE_ENABLED=false` turns the cache off, and a new `RESPONSE_CACHE_KEY_PREFIX` stops
reading every answer cached so far, which then expires. The cache is shared by every user of the
deployment, who share the one set of Polixis credentials anyway. `resolve_permanent_id`, served
straight from the spec, is not cached.

Every result of our tools says how fresh it is in `freshness`: `fetched_at`, when the server put
it together, and `cached_at`, null when all of it came from Polixis on that call, else when the
oldest cached answer it used was cached. The server instructions tell the agent to give the user
that as-of time when the data's age matters, as for sanctions or PEP status.

## The spec

`upstream/openapi.yml`, which the codegen reads, is built, never edited by hand: `uv run poe
merge-spec` takes Polixis's own spec, `spec/polixis-graph.openapi.json`, exactly as they sent
it, and applies the edits in `spec/merge_spec.py`. [`spec/README.md`](spec/README.md) lists what
those edits add to or correct in their spec and why, and how to take a new spec from them.

## Environment

`.env.example` lists every variable. Besides the server's own:

| Variable | |
|---|---|
| `UPSTREAM_CLIENT_ID`, `UPSTREAM_CLIENT_SECRET` | Polixis client credentials, exchanged for a bearer token at `UPSTREAM_TOKEN_URL` |
| `UPSTREAM_API_KEY` | Sent as `x-api-key` on every request |
| `UPSTREAM_API_URL`, `UPSTREAM_TOKEN_URL` | Default to Polixis production |
| `UPSTREAM_RETRY_*` | Retries any request on a 429 but a spent quota, and a GET on a 503. Which status Polixis' circuit breaker sends is not documented; add it to `statuses` once known |
| `UPSTREAM_MAX_CONCURRENT_REQUESTS` | At most this many Polixis requests in flight per process, 4 by default; the others wait for a free connection, so a 10-pid profile lookup does not reach Polixis as one burst |
| `UPSTREAM_QUOTA_COOLDOWN_SECONDS` | Once Polixis answers that the API key's quota is spent (a 429 with `x-amzn-errortype: LimitExceededException`), the process sends it nothing for this long, 900 by default, and every tool fails at once with a message saying so. Each process learns it on its own, so a spent quota costs one request per process per cooldown |
| `MCP_AUTH_MODE` | `zitadel` in a deployment, `none` locally |
| `ZITADEL_*` | Zitadel sign-in for the MCP's users |
| `DATABASE_URL` | Postgres, which holds the encrypted Zitadel sign-in state and the Polixis responses the tools reuse, each for at most an hour, deleted by a cleanup that runs once per cache TTL |

Every signed-in user shares the one set of Polixis credentials. A user's Zitadel token never
reaches Polixis.

## Deploy

`deploy/terraform/azure/polixis-mcp-secrets` creates the Key Vault placeholders for the Polixis
credentials, valued `<TO BE SET MANUALLY>`. Set each one by hand, then map it in the overlay's
ExternalSecret:

| Key Vault secret | Variable |
|---|---|
| `manual-polixis-mcp-client-id` | `UPSTREAM_CLIENT_ID` |
| `manual-polixis-mcp-client-secret` | `UPSTREAM_CLIENT_SECRET` |
| `manual-polixis-mcp-api-key` | `UPSTREAM_API_KEY` |

A placeholder with `create = false` in `secrets_placeholders` is skipped, for a secret that
already exists.

## Run it locally

```bash
cp .env.example .env    # fill in the UPSTREAM_ credentials
uv sync
uv run polixis-mcp      # http://127.0.0.1:8000/mcp, without sign-in
```

It opens Postgres at `DATABASE_URL` even without sign-in, so start one first, for example
`docker run -e POSTGRES_PASSWORD=dummy-password -e POSTGRES_USER=dummy-user -e POSTGRES_DB=polixis_mcp -p 5432:5432 postgres:17`.

`uv run poe ci` runs every check CI runs.

### Record Polixis once, replay it after

The API key's quota is small, so develop against recorded answers. `UPSTREAM_RECORDING_MODE`
puts `upstream/recording.py` between the client and Polixis:

| Mode | |
|---|---|
| `off` | The default, and the only mode a deployment uses |
| `record` | Answers a request already recorded from its recording, so nothing is paid twice; delete a recording to have it asked again. Sends the others, waiting `UPSTREAM_RECORDING_MIN_INTERVAL_SECONDS` (2 by default) between two, and saves the answer. Needs `UPSTREAM_RECORDING_BUDGET`, the most requests `ledger.jsonl` may hold across every run: past it nothing is sent. The first quota 429 writes `HALT`, and nothing is sent until you delete it |
| `replay` | Answers from the saved answers and sends nothing, the token request included. A request with no saved answer fails |

The answers go to `UPSTREAM_RECORDING_DIRECTORY`, `.mock-server-data/cassettes/` by default, one
file per request, and each sent request is a line in its `ledger.jsonl`. `.mock-server-data/` is
gitignored but for its README: it holds licensed data about real people, so it never leaves your machine or the team's download location, which `.mock-server-data/README.md` names, with what the folder holds and how to replay it. The
server refuses either mode unless `MCP_AUTH_MODE=none`. The client-credentials token is fetched
past the recorder, so no secret is ever saved.
