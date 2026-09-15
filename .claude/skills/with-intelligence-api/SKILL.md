---
name: with-intelligence-api
description: Explains how the With Intelligence v3 REST API works — the sign-in/refresh token flow, the uniform `{pagination, results}` envelope, the thin-listing/`*Extended`-detail split, resolving an investor or person by name to an id, the vocabulary endpoints every id-based filter is drawn from, what an empty result or a 403 means when entitlements are per-package, and the places the spec is wrong about what the API actually sends. Use this EVERY TIME you need to understand how some With Intelligence entity works or where its data comes from — before reading their OpenAPI spec or readme.io docs, adding a with-intelligence-mcp tool/feature, or exploring the live API.
---

# The With Intelligence v3 REST API

Plain REST, not JSON:API — there is no `relationships` envelope and no `?include=` side-loading,
so nothing here is discoverable from a response. The two ideas that explain most of it:

1. **A listing tells you who exists; the detail tells you about them.** Every listing record is
   `{id, name, updated_at}`. Everything else lives at `GET /{id}`, which returns the
   `*Extended` schema.
2. **Filters are vocabularies, not free text.** You filter by `primary_strategy_id`, not by
   "long/short equity". The ids come from ~70 small listing endpoints, and resolving a word to
   an id is a step you take before the query you actually wanted.

This file holds what the spec cannot tell you. Anything that *is* in the spec — which paths
exist, what a schema's fields are, what a listing can be filtered by — look up with `spec.py`
(§1) rather than expecting to find it here. Order of authority for *behaviour*: live `GET` >
readme.io guide/recipe > OpenAPI spec. Never design from the spec alone, and read §5 before
believing an empty result.

## 1. Tooling, and the public spec

Scripts and `.env` live in `services/with-intelligence-mcp/agent-explore/`. Run them through
`uv run` from the service root; the system interpreter has no httpx.

```bash
cd services/with-intelligence-mcp
uv run agent-explore/spec.py paths investor          # no credentials needed
uv run agent-explore/explore.py /v3/investors/2504   # needs .env
```

The spec is public and needs no auth — `GET https://api.withintelligence.com/v3/docs/json`,
OpenAPI 3.0, 143 paths, 267 schemas. Too big to read whole, which is what `spec.py` is for:

| Question | Command |
| --- | --- |
| What paths exist? | `spec.py paths [filter]` |
| What can I filter a listing by? | `spec.py params /v3/investors` |
| What fields does a record have? | `spec.py schema InvestorExtended` |
| What does a path return? | `spec.py response '/v3/investors/{id}'` |

`spec.py` caches to `.spec-cache/`, `explore.py` to `.probe-cache/` (both gitignored). Never
print credentials, and never POST anywhere except `/v3/auth/sign-in` and `/v3/auth/refresh`.

The website embeds the same ids as the API, so cross-checking is cheap: investor **2504** is
Virginia Retirement System. Probe a record you can also open in the UI before trusting a
field's meaning.

Human docs: <https://withapi.readme.io/docs/getting-started>, recipes at
<https://withapi.readme.io/recipes>, agent-oriented index at
<https://withapi.readme.io/llms.txt>. The guides carry field-level meaning the spec omits —
`docs/investors-1`, `docs/funds-1`, `docs/mandates-intentions-preferences` especially.

## 2. Auth

```
POST /v3/auth/sign-in     {"username", "password"}  ->  {"accessToken", "refreshToken"}
POST /v3/auth/refresh     {"refreshToken"}          ->  new tokens
GET  /v3/...              Authorization: Bearer <accessToken>
```

- **Access token lives 1 hour. Refresh token lives 30 days.**
- **There is no one-time passcode in this exchange.** The passcode in With Intelligence's onboarding
  mail is the *initial password*, spent once on `POST /v3/auth/set-password` by a human, before
  any programmatic use. Do not design a passcode step into a login flow.
- Whether `/v3/auth/refresh` *rotates* the refresh token or returns the same one is still
  unconfirmed against a live call. The service assumes it rotates: the stored session is
  rewritten on every refresh and the renewal is taken under a row lock, so two replicas cannot
  spend one token. Harmless if it turns out not to rotate; the reverse would not be.

## 3. Shape of every read

One envelope for all 143 paths, so one paginator serves everything:

```json
{ "pagination": { "page": 1, "page_size": 50, "count": 50, "total": 4321 },
  "results": [ { "id": 2504, "name": "Virginia Retirement System", "updated_at": "..." } ] }
```

`page` and `page_size` are the only paging controls; `count` is this page, `total` the whole
match. `GET /v3/<entity>/{id}` returns the `*Extended` schema — `spec.py schema InvestorExtended`
for its fields, which answer most of an IR question in one call. Reach for a separate endpoint
only when the detail record is not enough: `/v3/persons` for contacts beyond those embedded,
`/v3/investments` for roster entries with amounts.

**Every path documents** 200, 400, 401, 403, 404, 429, 500. So a 403 is a designed answer, not
an anomaly, and 429 is real even though no rate budget is published — measure headroom before
warming a cache.

## 4. Filters

Core listings filter by id, never by text: `primary_strategy_id`, `country_id`,
`investor_type_id`, `organisation_id`, and so on — `spec.py params <path>` for a listing's full
set. Each id comes from a matching two-field listing endpoint (`/v3/primary_strategies`,
`/v3/countries`, `/v3/investor_types`, …), roughly 70 of them.

So "investors in Texas with a macro mandate" is: resolve *macro* against
`/v3/primary_strategies` and *Texas* against `/v3/cities` or `/v3/countries`, then query
`/v3/mandates`. **Report a word you could not resolve** — silently dropping it returns a
confident answer to a different question.

Three filter families are worth knowing because they are easy to miss:

- `updated_at[from]` / `updated_at[to]` — a change-log window on everything. Articles use
  `post_date[from|to]` instead; investments additionally expose `deleted_at[from|to]`, which is
  the only way an exited position is visible at all.
- `exists[field]=true` to require a field be populated, `sort[<field>]`, and `id`/`name` as
  arrays for a batch fetch.
- Intentions carry numeric bands rather than ids (`ticket_size_usd_lower`/`_upper`,
  `investor_aum_lower`/`_upper`, …); mandates use `investor_aum[from|to]`.

## 5. Entitlements — why an empty result is ambiguous

`asset_class_group` (a "data solution") takes `hfm`, `pefi`, `pcfi`, `refi`, `cwi`, `iwi`, `sfo`.
Unique's agreement covers **hfm** (hedge funds) and **sfo** (wealth / family office). Responses
are auto-filtered to what the account is licensed for whether or not you pass it; passing it
narrowly keeps a hedge-fund question from paging through wealth records.

Two things are a **subscription add-on** — Intentions & Preferences:

- `/v3/intentions` (forward allocation intent), and
- the `preferences` object on `InvestorExtended`, whose own description says so.

Therefore **an empty result may mean "not licensed" rather than "nothing there"**, and the same
query answers differently per client. Anything built on this API has to distinguish the two and
say which it hit. Never report "this investor has no stated preferences" from an absent
`preferences`.

## 6. What live calls have established

Facts from real responses that the spec does not give, or gets wrong. Add to this list rather
than rediscovering them.

**The spec's array/object distinction is unreliable in both directions.** Five fields so far
arrive as the opposite of what the spec declares — an array delivered as an object keyed
`"0"`, `"1"`, …, or a single object delivered as a list of them. The authoritative list is
executable, not prose: `DELIBERATE` in
`services/with-intelligence-mcp/tests/test_spec_conformance.py` names each field and why it
deviates, and that test fails if a model drifts from the spec anywhere else. Consequences:

- Do not model a nested field on the spec's word alone. `with_intelligence_client.SEQUENCE`
  accepts either encoding for a field modelled as a list, `SINGLE` accepts a list for a field
  modelled as one object; apply them to **every** nested field, not only the ones already caught.
- An index-keyed object (`{"0": …}`) and a single record are told apart by whether every key is
  a digit — reading `.values()` off a single record turns `{"id": 4, "name": "Real Assets"}`
  into `[4, "Real Assets"]`.

**AUM is in millions.** An investor reporting `aum: 135900` with
`latest_aum.ranges_usd[0].label == "> $50bn"` is a $135.9bn fund. Publishing the raw number as
a plain figure is wrong by six orders of magnitude.

**Prose fields are HTML.** `summary` arrives as `<p>…<em><strong>…</strong></em></p>` with
`&nbsp;`, so it needs converting before a model reads it.

**Name matching is partial, not exact.** `?name=Virginia` returns 20 investors. So resolving a
short name is normally ambiguous, and a zero-result answer means no name contains the text —
not that the caller should try a longer form. The registered name may also carry a suffix
("Virginia Retirement System (VRS)").

**`?organisation_id=` on `/v3/persons` takes the investor's id**, and unlike the investor
record's `contacts`, the person listing carries names. Titles, seniority, email and `end_date`
live on `person_roles` in the *detail* record, so a roster with titles costs one listing call
plus one call per person. A person's roles span every employer they have had — pick the role
whose `organisation.id` or `org_entity_id` matches the investor, or you will attribute a
previous employer's job title to this one.

**The two contact counts disagree.** For investor 2504, the investor record embedded 64
`contacts` ids while `/v3/persons?organisation_id=2504` reported `total: 12`. Which is
authoritative is undocumented — report both rather than picking one.

**`organisation_type_id`** on `/v3/persons` maps `1 = Investor`, `2 = Manager`,
`3 = Consultant`.

**Entitlements observed:** the trial account returns no `preferences` on an investor record,
which is what an account without the Intentions & Preferences add-on sees.

## 7. Scope

**In scope (IR, hedge funds):** `investors`, `persons`, `investments`, `mandates`, `intentions`,
`funds`, `managers`, `articles`, `consultants`.

**Out of v1 scope:** the ~20 `deals*` paths (private markets), `indices`, and
`funds/private_market_benchmarks`. They exist and are documented; they answer PE and
private-credit questions rather than hedge-fund IR ones.
