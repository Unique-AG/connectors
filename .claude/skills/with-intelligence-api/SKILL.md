---
name: with-intelligence-api
description: Explains how the With Intelligence v3 REST API works — the sign-in/refresh token flow, the uniform `{pagination, results}` envelope, the thin-listing/`*Extended`-detail split, resolving an investor or person by name to an id, the ~70 vocabulary endpoints every id-based filter is drawn from, `updated_at[from|to]` change-log queries, and what an empty result or a 403 means when entitlements are per-package. Use this EVERY TIME you need to understand how some With Intelligence entity works or where its data comes from — before reading their OpenAPI spec or readme.io docs, adding a with-intelligence-mcp tool/feature, or exploring the live API.
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

Use this skill whenever the question is "how does entity X work / how do I get X out of With
Intelligence". Order of authority for *behaviour*: live `GET` (§5) > readme.io guide/recipe >
OpenAPI spec (§1). Never design from the spec alone — it describes shapes, never which ids
exist, how much data comes back, or what your subscription excludes.

## 0. Where the tooling lives

This skill file lives in `.claude/skills/with-intelligence-api/` and
`.cursor/skills/with-intelligence-api/` (where agents load skills). Scripts and `.env` live
in `services/with-intelligence-mcp/agent-explore/`. Run both through
`uv run` from the service root; the system interpreter has no httpx.

```bash
cd services/with-intelligence-mcp
uv run agent-explore/spec.py paths investor          # no credentials needed
uv run agent-explore/explore.py /v3/investors/2504   # needs .env
```

`spec.py` caches to `.spec-cache/`, `explore.py` to `.probe-cache/` (both gitignored). Never
print credentials, and never POST anywhere except `/v3/auth/sign-in` and `/v3/auth/refresh`.

## 1. The spec is public

```
GET https://api.withintelligence.com/v3/docs/json
```

OpenAPI 3.0, ~456 KB, **143 paths**, **267 schemas**, no auth required. Too big to read whole —
that is what `spec.py` is for:

| Question | Command |
| --- | --- |
| What paths exist? | `spec.py paths [filter]` |
| What can I filter a listing by? | `spec.py params /v3/investors` |
| What fields does a record have? | `spec.py schema InvestorExtended` |
| What does a path return? | `spec.py response '/v3/investors/{id}'` |

Human docs: <https://withapi.readme.io/docs/getting-started>, recipes at
<https://withapi.readme.io/recipes>, and an agent-oriented index at
<https://withapi.readme.io/llms.txt>. The guides carry the field-level meaning the spec omits —
`docs/investors-1`, `docs/funds-1`, `docs/mandates-intentions-preferences` especially.

## 2. Auth: password in, two tokens out

```
POST /v3/auth/sign-in     {"username", "password"}  ->  {"accessToken", "refreshToken"}
POST /v3/auth/refresh     {"refreshToken"}          ->  new tokens
GET  /v3/...              Authorization: Bearer <accessToken>
```

- **Access token lives 1 hour. Refresh token lives 30 days.**
- **There is no one-time passcode in this exchange.** The passcode in the vendor's onboarding
  mail is the *initial password*, spent once on `POST /v3/auth/set-password`
  (`{username, currentPassword, newPassword}`) by a human, before any programmatic use. Do not
  design a passcode step into a login flow.
- `POST /v3/auth/forgot-password` → emailed code → `POST /v3/auth/confirm-forgot-password`
  `{username, code, newPassword}` is the recovery path.
- Open question worth confirming against a live call: whether `/v3/auth/refresh` returns a
  *rotated* refresh token or the same one. It decides whether a stored session is rewritten on
  every refresh, and therefore whether a refresh needs a lock.

## 3. Shape of every read

**Listing** — `GET /v3/<entity>`:

```json
{ "pagination": { "page": 1, "page_size": 50, "count": 50, "total": 4321 },
  "results": [ { "id": 2504, "name": "Virginia Retirement System", "updated_at": "..." } ] }
```

One envelope for all 143 paths, so one paginator serves everything. `page` and `page_size` are
the only paging controls; `count` is this page, `total` the whole match.

**Detail** — `GET /v3/<entity>/{id}` returns the `*Extended` schema. `InvestorExtended` is the
one to know, because it answers most of an IR question in a single call: `aum` and `latest_aum`,
`type`, `summary`, `family_profile`, `address`, `website`, `year_of_incorporation`,
`asset_allocation_breakdown` (keyed by asset-class id), `primary_strategies` and
`secondary_strategies`, the whole investment-preference block (`investment_regions`,
`investment_countries`, `investment_fund_structures`, `investment_instruments`,
`investment_market_caps`, `investment_industries`, `investment_sectors`, `investment_sub_markets`,
`investment_capital_structures`, `investment_company_size_focuses`, `investment_attributes`),
`managers` (their current fund roster), `consultants`, `contacts` with `contacts_total`,
`allocation_calculations`, and `preferences`.

Reach for a separate endpoint only when the detail record is not enough: `/v3/persons` for the
contacts beyond those embedded, `/v3/investments` for roster entries with amounts and
`latest_as_of`.

**Every path documents** 200, 400, 401, 403, 404, 429, 500. So a 403 is a designed answer, not
an anomaly, and 429 is real even though no rate budget is published — measure headroom before
warming a cache.

## 4. Filters, and the vocabularies behind them

Core listings filter by id: `investor_id`, `manager_id`, `consultant_id`,
`primary_strategy_id`, `secondary_strategy_id`, `asset_class_id`, `country_id`,
`investor_type_id`, `investment_region_id`, `primary_industry_id`, `primary_sector_id`,
`market_cap_id`, `market_focus_id`, `capital_structure_id`, `approach_id`, `fund_structure_id`,
`status_id`/`sub_status_id`/`service_id` (mandates), `theme_id` (intentions),
`function_id`/`seniority_id`/`role_id`/`organisation_id` (persons), `firm_id`/`firm_type`
(articles). Each has a matching listing endpoint — `/v3/primary_strategies`, `/v3/countries`,
`/v3/investor_types`, `/v3/mandate_statuses`, … — of two-field records. Roughly 70 of them.

So "investors in Texas with a macro mandate" is: resolve *macro* against
`/v3/primary_strategies` and *Texas* against `/v3/cities` or `/v3/countries`, then query
`/v3/mandates`. Report a word you could not resolve — silently dropping it returns a confident
answer to a different question.

Also on most listings:

- `updated_at[from]` / `updated_at[to]` — a change-log window on everything. Articles use
  `post_date[from|to]` and `post_modified[from|to]` instead; investments additionally expose
  `deleted_at[from|to]`, which is how an exited position is visible at all.
- `sort[<field>]` = `asc` | `desc`; `id` and `name` as arrays for a batch fetch;
  `exists[field]=true` to require a field be populated.
- `asset_class_group` — see below.
- Intentions carry numeric bands rather than ids: `ticket_size_usd_lower`/`_upper`,
  `allocation_amount_usd_lower`/`_upper`, `investor_aum_lower`/`_upper`, `fund_count_lower`/
  `_upper`. Mandates use `investor_aum[from|to]`.

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

## 6. Verifying against the live instance

The website embeds the same ids as the API, which makes cross-checking cheap: investor **2504**
is Virginia Retirement System, and `withintelligence.com` URLs for a record carry its id. Probe
a record you can also open in the UI before trusting a field's meaning.

Worth establishing by live GET, because the spec cannot say: how big each vocabulary actually is
(it sets cache sizing), what `hfm` filtering does to a result count, which `InvestorExtended`
fields are densely populated versus mostly null, and what a 429 costs.

## 7. Entities, and which belong to v1

**In scope (IR, hedge funds):** `investors`, `persons`, `investments`, `mandates`, `intentions`,
`funds` (+ `funds/open_end_performances`, `funds/closed_end_performances`), `managers`,
`articles`, `consultants` (+ `/consultants/{id}/investors`, `/consultants/{id}/mandates`).

**Out of v1 scope:** the ~20 `deals*` paths (private markets), `indices` and their constituents
and performances, and `funds/private_market_benchmarks`. They exist and are documented; they
answer PE and private-credit questions rather than hedge-fund IR ones.
