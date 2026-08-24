---
name: backstop-api
description: Explains how Backstop's JSON:API-style REST responses work — the relationships/links envelope, resolving a person/organization to an id, following relationships to related data (activities, notes, entity-relationships, ...), the `?include=` side-loading param, and mandatory pagination — and how to read this instance's swagger plus the Elevio product docs together. Use this EVERY TIME you need to understand how some Backstop entity works or where its data comes from — before reading the Backstop swagger or Elevio help articles, adding a backstop-mcp tool/feature that walks relationships, or exploring the live Backstop API.
---

# The Backstop REST API

Backstop's API is JSON:API-shaped but not fully JSON:API compliant. The one idea that explains
almost everything: **every resource tells you how to reach everything connected to it.** You never
have to guess an endpoint — you resolve a record once, then read its own `relationships` to find
the next one.

Use this skill whenever the question is "how does entity X work in Backstop / how do I get X's
data out of Backstop". Combine three sources, in this order of authority for *behaviour*:
live `GET` (§6) > Elevio article (`docs.py`) > instance swagger (`explore.py`). Never design
from swagger or Elevio alone.

## 0. Where the docs live

This skill file lives in `.claude/skills/backstop-api/` and `.cursor/skills/backstop-api/`
(where agents load skills). The scripts and `.env` live in
`services/backstop-mcp/agent-explore/`. Do not send the API token to Elevio, and do not
POST to `BACKSTOP_BASE_URL`.

**A. Instance swagger — `explore.py`, API token.** Same host as the CRM:

```
GET {BACKSTOP_BASE_URL}/backstop-api-swagger.json
```

`Authorization: Basic` username + API token, plus `token: true`. Swagger 2.0, ~1.4 MB,
~1167 paths. Endpoints, filter fields, and sort enums for *this* instance. Far too big to
read whole: cache under `.probe-cache/` and `grep`/`jq` one path. Do not dump it into the
conversation. Skip `/backstop/api-docs/` (HTML UI, web session); the UI itself just GETs
that JSON file.

**B. Product docs — `docs.py`, web username/password.** Elevio at
`https://backstopsolutions.elevio.help` (forced SSO via
`https://help-prod.backstopsolutions.com/backstop/sso/elevioStart.jsp`). Anonymous GETs
are 401 shells; after SSO the HTML carries `window.initialData`. The API token cannot
read this. `docs.py` may POST `j_username`/`j_password` to help-prod `j_security_check`
only. Set `BACKSTOP_DOCS_USERNAME` and `BACKSTOP_DOCS_PASSWORD` in
`services/backstop-mcp/agent-explore/.env` (copy `.env.example`; username may fall back
to `BACKSTOP_SERVICE_USERNAME`). Cache is `agent-explore/.docs-cache/` (gitignored).

If either web credential is missing, **stop and ask the user to put them in
`services/backstop-mcp/agent-explore/.env` before running `docs.py` or fetching any
Elevio page.** Do not guess, do not try the API token, and do not start a docs request
hoping it works. After they are set, then `tree` / `category` / `article`.

```
cd services/backstop-mcp
uv run python agent-explore/docs.py tree
uv run python agent-explore/docs.py category 21          # REST API
uv run python agent-explore/docs.py category 40          # Backstop Fundamentals
uv run python agent-explore/docs.py article 941
uv run python agent-explore/docs.py article 757 --refresh
```

`tree` then `category` then `article`. Category pages list children; they do not inline
bodies. Prefer `body_text` from `article`. Do not print whole categories into the
conversation. REST API hub is category **21**; fundamentals is **40**.

If `docs.py` still exits asking for the web password, ask again — do not invent Elevio
content from swagger or from Confluence PDFs unless they ask.

Don't reintroduce a checked-in or `.docs-local/` swagger. Swagger is authoritative about
*what endpoints exist* but weak about behaviour — `parameters` are often empty or wrong
(§5, §6). Elevio is the product's intent; a live response still wins.

## 1. The shape of every resource

```json
{
  "id": "27871657",
  "type": "accounts",
  "attributes": { "name": "William Tobin Pratt", "...": "..." },
  "relationships": {
    "activities": {
      "links": {
        "self": "https://.../accounts/27871657/relationships/activities",
        "related": "https://.../accounts/27871657/activities"
      }
    },
    "owner": { "links": { "self": "...", "related": "https://.../accounts/27871657/owner" } },
    "notes": { "links": { "self": "...", "related": "https://.../accounts/27871657/notes" } }
  },
  "links": { "self": "https://.../accounts/27871657" }
}
```

- `attributes` — the record's own fields.
- `relationships` — one entry per thing this record links to (accounts commonly have 20-30:
  `activities`, `notes`, `documents`, `owner`, `entityRelationships`, `product`, `values`, ...).
  Each entry's `links.related` is a real, fetchable URL for that relationship's data —
  `relationships.activities.links.related` on an account **is** `GET /accounts/{id}/activities`.
- `links.self` — the canonical URL for this resource itself.

This repo already models this envelope in
`src/backstop_mcp/backstop_client/json_api.py` (`BackstopApiResource`, `BackstopRelationship`).
Reuse those types rather than hand-rolling relationship parsing again.

## 2. Two ways to reach related data

**A. Follow `relationships.<name>.links.related` (default choice).** A direct `GET` against
that URL, paginated independently like any other list endpoint. This is the right choice for
anything that can be large — `activities`, `notes`, `documents` — because it gives you full
control over `page[limit]`/`page[offset]` on that specific collection.

**B. `?include=<name1>,<name2>` on the resource GET.** Backstop side-loads the named
relationships' full resources into a top-level `included` array on the *same* response, e.g.:

```
GET /people/{id}?include=activities
```

The primary resource's `relationships.activities.data` becomes the `{type, id}` pointer(s); the
actual resource bodies show up in `included`, matched by `(type, id)` — not nested inside
`attributes`. `follow_included()` / `included_by_type()` in `json_api.py` already do this
matching. Which relationship names an endpoint accepts via `include=` is Backstop's choice per
endpoint, not universal (e.g. `custom-field-definitions` only accepts `include=lovSet`) — check
the swagger path for the endpoint you're calling.

Prefer (A) for anything you plan to paginate or that might be large; reach for `include=` mainly
when you need one or two small/to-one relationships alongside the primary resource in a single
round trip.

## 3. Resolve a party to an id before reading relationships

You cannot walk relationships from a name — you need the record's id first. The read path is
always: **resolve → GET by id → follow relationships**, never a `POST` (POST endpoints in the
swagger are for creating/updating records, not searching).

Two resolution primitives Backstop exposes, both `GET`:

- `GET /people?filter[email][eq]={email}` (also `email2`, `email3`) — exact-match lookup.
- `GET /quick-search?filter[searchText][eq]={text}&filter[searchTypes][eq]={type}` — prefix-
  anchored name lookup (`Dispersion` misses `Capstone Dispersion`; `Capstone Disp` hits).
  Collection filters also accept `like`: `filter[name][like]` on organizations, products,
  activity-tags, and system-users; `filter[lastName][like]` on people (`name` is not a
  people LIKE field). Do not send `[like]` to `/custom-field-definitions` — it is accepted
  and ignored.

This repo already implements both — see `features/party_resolver/search.py`
(`search_by_email`, `quick_search`) and `features/party_resolver/resolve.py`. Reuse these instead
of calling `/quick-search` or `/people` directly from new code.

Once you have an id: `GET /{type}/{id}` returns the resource with its `relationships` map, and
`relationships.activities.links.related` (or any other relationship) is your next request.

## 4. Pagination is mandatory — lists are massive

Every list endpoint (a filtered collection, a followed relationship, `/quick-search`) is
paginated via `page[limit]` / `page[offset]` plus a `links.next` URL and
`meta.totalResourceCount` on the response. **Always pass an explicit page size on the first
request** — an unbounded list call against a real Backstop instance can be tens of thousands of
records.

- Param names are configurable (`BackstopConfig.page_limit_param` / `page_offset_param`,
  default `page[limit]` / `page[offset]` — see `config.py`), because Backstop silently ignores
  an unrecognized query param rather than erroring, so a typo here fails silently.
- `BackstopClient.paginate()` (`backstop_client/client.py`) already applies a default page size
  (`default_page_size`, or `report_page_size` for `/reports` and `/analytics` paths) and walks
  `links.next` for you via `paginate_all()` (`backstop_client/pagination.py`). Use it for any new
  collection fetch rather than hand-rolling a `links.next` loop.
- `included` entries repeat across pages of the same chain when `?include=` is combined with
  pagination; `paginate_all()` already dedupes them by `(type, id)`.

## 5. Sorting collections with `sort=`

Many list endpoints accept a top-level `sort={field}` query param — single field name for
ascending, a leading `-` for descending (e.g. `sort=-modifiedTimestamp`). The swagger encodes
this oddly: the "path" for e.g. funds is literally
`/funds/?filter[{filterField}][{filterOperator}]={filterValue}&sort={sortField}`, with
`filterField`/`filterOperator`/`filterValue`/`sortField` listed as swagger "path" parameters —
that's a swagger-authoring quirk, not a real path segment. In practice `sort` is just an
independent query param, usable with or without a `filter[...]` alongside it.

What's genuinely per-endpoint and worth checking before assuming a field sorts:

- **Sortable fields are an explicit enum per endpoint**, not "any attribute." `/people` sorts on
  `createdTimestamp, email, email2, email3, id, lastName, modifiedTimestamp, name, otherId` (each
  also with a `-` variant); `/contact-emails` only sorts on `id`. Check the swagger path for the
  specific endpoint rather than assuming a field you can see in `attributes` is sortable.
- **Only one field per request is documented** — no comma-separated multi-field sort appears
  anywhere in the swagger.
- **Some sub-collections document no `sort=` at all** (e.g. a documented case in
  `features/custom_fields/values.py`, which sorts a time-series relationship client-side for this
  reason). An empty `parameters` list for an endpoint doesn't necessarily mean `sort=` is silently
  accepted — Backstop drops unrecognized query params rather than erroring (see pagination note
  above), so confirm empirically with `explore.py` (below) before relying on it.

## 6. Exploring a Backstop entity against the live API

**This is the default way to answer "how does entity X work".** Don't reason from the swagger
alone — its `parameters` are often empty/uninformative (see e.g. the `/people` GET entry), so real
responses are more reliable. The loop, using `services/backstop-mcp/agent-explore/explore.py` for every request:

1. **Fetch a small page of the entity.** `GET /{type}` with `page[limit]=5` (never unbounded —
   §4). That one response already tells you the attribute set, which `relationships` the type
   exposes, and `meta.totalResourceCount` for how big the collection really is.
2. **Pick a few concrete records** from that page — ideally not all alike (one that looks fully
   populated, one sparse) so you don't mistake one record's nulls for the schema.
3. **Dive into each.** `GET /{type}/{id}` for the full resource, then follow the
   `relationships.<name>.links.related` URLs that look relevant, again with a small `page[limit]`.
   That's how you discover what actually hangs off the entity, which relationships fan out to
   thousands of records, and which attributes are populated in practice vs. always `null`.
4. **Confirm the query surface you'll actually use** — does the `filter[field][op]` you want
   return anything, does `sort={field}` change the order (§5), does `include=` accept the
   relationship name (§2)? Backstop silently ignores unrecognized query params instead of erroring,
   so "no error" is not confirmation — compare responses with and without the param.
5. **Cross-check the swagger** (§0) only for the specific path, to see the documented filter/sort
   enums. Where swagger and a real response disagree, the response wins.

**2-minute timeout — if it expires, the API is down.** Every live probe (including `explore.py`)
times out after **2 minutes** (`httpx` `timeout=120.0`). When you run `explore.py`, wait the full
2 minutes (`block_until_ms` ≥ 120000); do not kill the process earlier. If that deadline is hit —
timeout, hang, or a connection that never returns — treat the Backstop API as down. Do not retry,
do not probe other paths, and do not invent a response from swagger. Tell the user you cannot
probe the API and ask what they want to do next.

Build **one** small reusable CLI script and drive it repeatedly for however many requests the
exploration needs, rather than writing a fresh throwaway script per request.

Credentials for this live instance are a service account, not a per-user OAuth credential, and
they live in `services/backstop-mcp/agent-explore/.env` (copy `.env.example` there; do not
export that file into your shell):

```
BACKSTOP_BASE_URL
BACKSTOP_SERVICE_USERNAME
BACKSTOP_SERVICE_API_TOKEN
```

This instance is **read-only for agents**. Probe with `GET` only. Never `POST`/`PATCH`/`PUT`/`DELETE`
against `BACKSTOP_BASE_URL`, and never send a request body. Do not print credentials.

Auth is `Authorization: Basic base64(username:token)` plus a `token: true` header. The script
is `services/backstop-mcp/agent-explore/explore.py`: always `GET`s, loads that folder's `.env`,
writes every response to `agent-explore/.probe-cache/` (gitignored), and prints the JSON
body. Do not `raise_for_status` — 400s are part of the cache. Reuse cached files before
hitting the API again. Do not rewrite this script.

Run from `services/backstop-mcp` so `uv run` picks up the service venv:

```
# 0. instance swagger (large — write to cache / grep, do not print)
uv run python agent-explore/explore.py /backstop-api-swagger.json
# 1. small page of the entity
uv run python agent-explore/explore.py /people -p "page[limit]=5" -p "page[offset]=0"
# 3. dive into a few of the ids that came back, then follow their relationships
uv run python agent-explore/explore.py /people/12345
uv run python agent-explore/explore.py /people/12345/activities -p "page[limit]=5"
# 4. confirm the query surface
uv run python agent-explore/explore.py /custom-field-definitions -p "include=lovSet"
```

## 7. Building a new backstop-mcp feature: explore before you design

Don't jump from a feature request straight to a design or implementation — the data model is
discovered from real responses, not assumed from field names or the swagger schema alone. For any
new backstop-mcp tool/feature:

1. **Explore first.** Read the matching Elevio article via `docs.py` (category **21** for
   REST API topics, **40** for fundamentals) so you know the product's intent, then run the
   §6 loop against the live instance for each resource the feature touches. Do it with the
   user in the loop: share what the shape looks like and flag anything surprising (an
   attribute that's `null` more often than not, a relationship that fans out to thousands
   of records, a field whose enum doesn't match its label). If a probe hits the 2-minute
   timeout, stop: you cannot probe the API — tell the user and ask what to do next; do not
   design from swagger or Elevio alone.
2. **Build the shared understanding before picking an approach.** Agree with the user on which
   resource(s), relationships, and fields the feature actually needs once you've both seen real
   data, not the names you'd guess from the swagger alone (whose `parameters` are often
   empty/uninformative — see §5-6).
3. **Only then list the concrete API parameters the feature will call with** — which
   `filter[field][operator]` clauses, `sort=` field, `include=` relationships, `fields=` sparse
   fieldset, and page size — as an explicit list before writing the implementation. That list is
   what the `BackstopClient` call(s) turn into; agreeing on it first avoids re-discovering mid-
   implementation that a field doesn't filter or doesn't sort.

This mirrors how the rest of this repo was built: `features/party_resolver/search.py` and
`features/custom_fields/values.py` both encode things (fuzzy-search limitations, a relationship
with no `sort=`) that only came from exploring real responses, not from reading the swagger cold.
