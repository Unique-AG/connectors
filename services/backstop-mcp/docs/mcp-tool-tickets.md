# backstop-mcp — tool enhancement tickets

Product backlog for a **tenant-agnostic** Backstop MCP. Capstone's Keystone deck was the discovery
source ([`keystone-dashboard-mapping.md`](keystone-dashboard-mapping.md)), not the spec.

**Build strategy:** ship general primitives (read + write) so an agent can discover each tenant's
vocabulary — tabs, groups, field names, tags, saved reports — and run that tenant's workflows. Do
**not** ship Capstone-named tools, hardcoded field ids, or dashboard arithmetic. No ticket here may
hardcode a client's field names, field ids, dropdown values, stage names, strategy names or
thresholds.

Each ticket states:

1. **UI surface** — where a user finds this data in Backstop, described generically, with the Capstone
   instance as a worked example
2. **What it represents** — the semantics, and which part is universal vs. tenant-defined
3. **Implementation** — what to build, and how it stays general

---

## Status at a glance

Confluence [Common Workflows](https://unique-ch.atlassian.net/wiki/spaces/Product/pages/2435088393/Backstop+MCP+Connector+Common+Workflows+User+Requirements) §4A–E.

### Shipped — §4A lookup (do not rebuild)

Ten tools, all one party or one product. Stage names, product names, and custom-field *catalog*
entries already come from the instance at runtime.

| Workflow | Tool |
| --- | --- |
| Last meeting / call / email / note / document with X | `get_activity_history`, `get_activity_detail` |
| Current balances, invested/redeemed, status by fund | `get_product_positions` |
| Accounts a party owns (listing and status only) | `get_accounts_for_party` |
| Emails and locations | `get_person` / `get_organization` + `include=email_addresses,locations` |
| Pipeline for one org | `get_opportunities` |
| People at an org (current vs former) | `get_people_for_party` |
| Custom-field catalog | `list_custom_fields` |

Also shipped: Party ID resolve; retired-email and former-employment flags.

Known general holes in that surface: tags missing on the timeline; custom-field *values* are a flat
dump (duplicate names); party accounts have no balances.

### Build — general MCP + writes

This is the product. An agent with these can figure Capstone (Grade, campaigns, strategy tags, the
page-11 briefing) without us encoding it.

| Priority | Tickets | Why |
| --- | --- | --- |
| **1 — make reads usable** | **A1, A2, A3**, **E1, E2**, **L1, L2** | Join values to tab/group/`definitionId`; fix catalog dupes; list groups so the agent discovers campaigns and "tier" sections; put tags on the timeline; cheaper positions + balances on a party's accounts. |
| **2 — writes** | **K1–K4** | Log activity, patch opportunity stage/amounts, patch custom fields (catalog-validated), correct contacts. In scope now. Start with draft-for-confirmation; catalog validation is mandatory for K3. Client question 8 decides guardrails and which fields get first-class parameters — it does not block a generic write surface. |
| **3 — tagged outreach** | **E3, E4** | Tag-scoped counts and "everything with this party about topic X". Standard Backstop, not Capstone. Answers Confluence §4D's second bullet. |
| **4 — optional general primitives** | **B1, C1, C3, F1, I1, J1, H3, H4** | Probe filters; firm-wide opportunities; system-users; per-party engagement counts; run a *saved* report; capital flows; person extras by type; tasks. Ship when a workflow needs them. **I1 before any cohort walk (C2).** |

A4 (ordinal parsing) is a shared utility if/when an agent or a later aggregate needs it — not a
product tool. A5 (semantic profile) is **optional deployment config**, not a dependency: tools stay
fully usable with no profile. The agent uses A1–A3 (and `list_custom_fields` today) to learn a
tenant.

### Do not build — Capstone-shaped; agent computes

Leave these as agent (or skill) projections over A1/A3/E2/C1/I1. Capstone names in parentheses are
worked examples only.

| Ticket | Why it is out |
| --- | --- |
| **D1 `get_pipeline`, D2 derived metrics, D3 RAG/staleness** | Capstone columns (Grade, Status, Weighted Value, Sales Prob Adj, Imminent, 14/30/90 bands). Agent joins party custom fields onto `get_opportunities` / C1 and does the arithmetic. |
| **G1 cohort index, G2 Original Status, C2 `find_parties`** | "All Grade = Focus" cannot be filtered server-side. Prefer **I1** (`run_report`) if the tenant has a saved report. C2 is an expensive last resort, not a Focus Groups tool. |
| **H1 `get_party_profile`** | Capstone page-11 panel (17 strategy dropdowns, AUM field names). Agent selects fields from A1/A3. |
| **F2, F3, H2, T4.5 `list_campaigns`** | Firm-wide engagement and peak-balance are later, if needed. Campaigns are groups with a flag field — A3 shape summary, never a name-keyed campaign tool. |
| **T6.3 / targets** | Not in Backstop. Caller supplies them. |

Epic bodies below are kept as design notes (UI surface, API shape, constraints). Status is this
section, not the epic heading.

---

## 0. The generalisation rule

Everything below rests on one distinction.

**Universal Backstop mechanics** — safe to build tools directly on:

- party resolution; the custom-field catalog *structure* (tab → group → field → type → select options);
  custom-field values on records; opportunity standard attributes (`stage`, `stageHistory`,
  `probability`, `requestedAmount`, `allocatedAmount`, `expectedInvestmentDate`, `closedDate`); the
  `representative` relationship; activity tags; the five activity types; accounts, products and their
  dated series; subscriptions/redemptions; tasks; Report Builder reports; `/resource-metadata`;
  POST/PATCH on those same resources.

**Tenant vocabulary** — must be discovered at runtime (A1–A3, `list_custom_fields`, `list_activity_tags`)
or optionally supplied as configuration (A5). Never compiled in:

- which custom field means "tier" (Capstone: `Grade`), "relationship stage" (Capstone: `Status`),
  "investor lifecycle" (Capstone: `Investor Status`); which set of fields is the strategy/product
  interest matrix (Capstone: 17 dropdowns); which custom-field groups are outreach campaigns; the
  dropdown vocabularies themselves; stage names; RAG thresholds; targets.

**A5 is not the bridge.** The bridge is a usable catalog and resolved values (A1–A3). A5 is
ergonomics for a deployment that wants role names (`tier`, `relationship_stage`) instead of
definition ids. Tools must remain fully usable with no profile configured — never guess, never fall
back to matching English labels.

**Ordering note.** Build A1–A3, E1–E2, L1–L2, then writes (K), then tagged retrieval (E3–E4). Firm-wide
and report tickets (C1, I1, …) are optional primitives. Epics D, G, and H1 stay in this file as
design notes for what an *agent* can project — they are not connector work.

Client questions in
[§7.2 of the requirements page](https://unique-ch.atlassian.net/wiki/spaces/Product/pages/2435088393/Backstop+MCP+Connector+Common+Workflows+User+Requirements)
still matter for Capstone demos and for write-back guardrails (question 8); they do not gate the
general read/write surface.

---

## Epic A — Custom-field semantics layer

The single highest-leverage epic. **A1–A3 are product work** — they are how an agent discovers any
tenant's vocabulary (Capstone's Grade, another client's equivalent) without us encoding it. A4 is a
shared utility if aggregates need it. A5 is optional config.

Today custom-field values come back unusable.

### A1 — Return resolved custom-field values on party reads

**UI surface.** Any record page's custom tabs and sections. Generic shape: Record → *tab* → *section* →
labelled fields. Capstone example: Organization → **Investor Information** tab → **Investor Status**
section holds tier, relationship stage, lifecycle status, AUM figures and the strategy matrix.

**What it represents.** The tenant's own CRM vocabulary — the fields IR teams actually maintain and
report on. Universal: that custom fields exist, are grouped, and are typed. Tenant-defined: everything
about their meaning.

**Implementation.** `get_organization` / `get_person` currently return `regularCustomFieldValues` as a
flat list. On a live Capstone org that is ~130 entries where the name `Status` appears 8 times with 8
different `definitionId`s, `Notes` 6 times and `Initial Target List` 7 times — the model cannot tell them
apart. Join values to their definitions and return `definitionId`, `name`, `tab_name`, `group_name`,
`field_type`, plus the resolved value. Add selection parameters (by definition id, by tab, by group, by
name) so callers can request a slice instead of the whole dump.

Two behaviours to get right, both general:

- **`ENTITY`-typed values** carry a `resourceType`/`resourceId` reference (Capstone uses this for
  consultants and contacted individuals). Surface them as resolvable party references, not raw blobs.
- **Values outside the current option list must be preserved and flagged**, not dropped. Live example:
  an org holds `CGM = "Dialogue"` while that field's options are `4 - Client … 0 - Not Relevant`. Legacy
  values are a general consequence of tenants editing dropdowns over time.

*Depends on:* A2. Product-critical: this is what lets an agent tell duplicate field names apart
without a semantic profile. D/G/H stay agent-side projections over this output.

### A2 — Fix `list_custom_fields` duplication

**UI surface.** None — this is the catalog behind every custom tab.

**What it represents.** The definition catalog. Universal.

**Implementation.** For `organizations` the tool returns 1028 entries for 257 unique definition ids
(~4× duplication), all with `resource_type = organizations`. Find whether the duplication is in the
upstream pagination walk or our own accumulation, dedupe, and add a regression test. Cheap and blocking.

### A3 — `list_custom_field_groups`

**UI surface.** The tab and section headings themselves, on any record type.

**What it represents.** How a tenant has organised its CRM. Universal mechanism. This is the tool that
lets an agent *discover* tenant vocabulary rather than being told it: given the group listing, an agent
can find the section holding tier/stage fields, or the per-campaign outreach sections, without us naming
them.

**Implementation.** Derive tab/group structure from the catalog (A2) and return groups with their field
membership and a shape summary — field count, types present, whether the group contains a boolean/Yes-No
flag alongside date and free-text fields.

That shape summary is what makes **campaign discovery general**. A Backstop outreach campaign is
structurally a group containing a flag field plus contact-date/response/notes fields; it is recognisable
from structure alone. Capstone's `Converts - Feb 2026 Targeting` (2026 tab) and
`Dispersion - Leveraged Share Class` (2025 tab) both match this shape, as do their 2021–2024 equivalents.
Do **not** ship a `list_campaigns` tool keyed on names like `Target List` — expose the structure and let
the caller identify campaigns, optionally assisted by A5.

*Answers Confluence §7 D1 generically.*

### A4 — Ordinal-coded dropdown parsing

**UI surface.** Any dropdown whose options are prefixed with a rank. Capstone examples: relationship
stage `0 - No Dialogue` … `6 - Cross Sell 2`, and the strategy matrix `0 - Not Relevant` …
`4 - Client`.

**What it represents.** A widespread Backstop convention for encoding progression in a picklist, which
is what makes averaging into an index meaningful. The `N - Label` pattern is a convention, not a Backstop
feature — so treat it as a *detected* property, never assumed.

**Implementation.** A shared utility that, given a field definition, detects whether its options are
ordinally coded and exposes `ordinal` alongside `label` on values. Must handle: duplicate ordinals with
different labels (Capstone has both `0 - No Dialogue` and `0 - Dead`), non-conforming legacy values
(return `ordinal = null`, do not coerce), and fields that are not ordinal at all. Consumers must report
unparseable values rather than silently excluding them from aggregates.

*Blocks:* G1 (agent-side, if ever). Not required to ship A1–A3.

### A5 — Tenant semantic field profile

**Status: optional.** Requirement 5 on the requirements page is satisfied by A1–A3 (the agent looks
up the tenant's fields). A profile is only for a deployment that wants role names instead of
definition ids.

**UI surface.** None — this is deployment configuration.

**What it represents.** An optional mapping from *semantic role* to *this tenant's definition ids*.

**Implementation.** Optional per-deployment config mapping roles to definition ids or catalog paths
(`tab / group / name`), e.g. `tier`, `relationship_stage`, `lifecycle_status`,
`strategy_interest_set` (a list), `campaign_flag_pattern`, plus threshold sets. If a tool accepts a
role name and no profile is configured, return a clear, actionable error naming the role and pointing
at `list_custom_fields` / `list_custom_field_groups` — never guess, and never fall back to name
matching on English labels.

Validate the profile against the live catalog at startup and surface drift (a definition id that no
longer exists, or a role pointing at a field whose type changed) rather than failing at query time.

Do not make A1, E, C1, or K wait on this.

*Depends on:* A2, A3. Only needed if a deployment chooses to use roles.

---

## Epic B — Capability discovery

### B1 — Probe and pin Backstop's filter/sort/include surface

**UI surface.** None.

**What it represents.** What the API can actually do per tenant. Backstop's `filterField` is a closed
enum per collection, operators are only `eq, neq, gt, ge, lt, le` (no `in`, no `like`), and **no
collection can filter on custom fields**. Our own code already documents the published swagger being
wrong in both directions on this tenant — `filter[isOpen]` returns 400 despite being documented, and
`sort=` is silently ignored on opportunity sub-collections.

**Implementation.** A probe (script plus recorded tests) that walks `/resource-metadata/?filter[resourceType][eq]=<type>`
and makes live confirmation calls for the filters the later epics depend on: `filter[representative.name]`
on `/opportunities`; `filter[activityTagIds]` and `filter[startTimestamp]` on `/meeting-or-calls`;
`filter[transactionDate]` on subscriptions; `filter[entityId]`/`filter[entityType]` on `/tasks`. Record
results as a capability matrix in the repo.

**Critically, determine whether firm-wide activity collections can be attributed to a party.** The
`/meeting-or-calls`, `/notes` and `/documents` include lists appear to contain no entity/party/organization
relationship. If that holds, tag-filtered *counts* are cheap while anything needing "which investor was
this with" requires walking organizations instead. **This one finding sets the scope of Epic F.**

Do this before C1 / E3 / F2 / J1 — not before A1–A3, E1–E2, L, or K. Party-scoped work does not
depend on the firm-wide filter matrix.

*Blocks:* C1, C2, E3, F2.

---

## Epic C — Cross-party query primitives

Backstop has firm-wide collections and the connector wraps none of them. All 10 existing tools are
party-scoped: resolve one party, fetch its children.

### C1 — `find_opportunities` (firm-wide pipeline query)

**UI surface.** The pipeline/opportunity list view, filtered across all parties rather than opened from
one record. On a party record the same data appears under the **Opportunities** tab.

**What it represents.** The forward-looking book. Universal: opportunities, stages, probability, amounts,
dates. Tenant-defined: stage names and any custom fields on the opportunity.

**Implementation.** Wrap `GET /opportunities` with
`include=investor,representative,stage,stageHistory,product`.

The important discovery: **`investor` resolves to the organization**, whose custom-field values arrive
inline. So a single paginated walk yields opportunities *and* their party's tenant-defined fields — no
second collection walk, no two-sided join. `filter[representative.name]` is the only relationship-path
filter in the whole API and allows server-side per-rep slicing; stage, product and amount filtering must
be client-side.

Expose date-window, open/closed, rep, stage and custom-field-value filters in the tool signature, but be
explicit in the docstring about which are server-side and which are applied after fetch, since that
determines cost. Needs bounded pagination and result caps; `paginate(parallel=True)` already exists.

*Depends on:* B1, A1.

### C2 — `find_parties` (cohort query with custom-field predicates)

**UI surface.** A filtered organization/person list, or the equivalent saved report.

**What it represents.** "Which investors match these criteria" — the general primitive behind every
cohort view: tier cohorts, relationship-stage distributions, campaign target lists, lifecycle segments.
One tool, many tenant-specific questions.

**Implementation.** `GET /organizations` filters only on `createdTimestamp`, `modifiedTimestamp`, `name`,
`otherId`, `emailDomains`, `matchingDomains`, `entityTypeId`. Custom fields are **not** filterable, so
predicates on tenant fields require a bounded full collection walk with client-side filtering. Build it
that way, honestly: caps, pagination, caching, and a response that states how many records were scanned
and whether the result was truncated.

Predicates should be expressed generically — `definition_id` (or A5 role) plus operator plus value(s),
combinable — with `include=representative`. This is the single tool that serves Capstone's Focus Groups
page *and* its campaign target lists *and* any other tenant's equivalents.

**Scope this only after I1.** If a tenant's cohorts already exist as saved reports, `run_report` gets the
same answer with server-side custom-field filtering and a fraction of the cost.

*Depends on:* B1, A1. *See also:* I1, client question 9 (cohort sizes). Optional A5 roles; never required.

### C3 — `list_system_users`

**UI surface.** Admin user list; also the Representative field on any record.

**What it represents.** Internal staff — relationship managers and IR reps. Universal. Needed because
almost every management view groups by representative.

**Implementation.** Wrap `GET /system-users` (filterable on `name`, `lastName`). Small.

---

## Epic D — Pipeline reporting

**Out of product scope** (see Status at a glance). Design notes for an *agent* projection over C1 /
`get_opportunities` + A1, not connector tools. Capstone pages 5–6.

Deck pages 5–6. Natively supported by the API; do not ship as `get_pipeline`.

### D1 — `get_pipeline`

**UI surface.** Party record → **Opportunities** tab for one party; the pipeline report view for the book.
Opportunity custom fields live under their own tab/section — Capstone: **Master Pipeline** tab →
**Pipeline Entries** section.

**What it represents.** One row per live opportunity, enriched with the party's tier and relationship
stage so management can see both deal state and relationship state together.

**Implementation.** A projection over C1: representative, party name, party tier and relationship stage
(via A5 roles or explicit ids), product, stage, expected investment date, amount, both probabilities,
plus any caller-requested opportunity custom fields.

**Name the two probabilities distinctly.** The standard `probability` attribute and a rep-entered
probability custom field are both real, both used, and differ on the same record. In the Capstone
sandbox one opportunity carries `requested_amount` 500M with standard `probability` 0.15 while the
custom field reads 10%. Conflating them silently corrupts every downstream total. The *existence* of a
rep-entered probability custom field is tenant-specific; the standard attribute is universal.

Likewise treat an "imminent"-style boolean as a caller-nominated custom field, not a built-in concept.

*Depends on:* C1, A1, A5.

### D2 — Derived pipeline metrics

**UI surface.** The summary bands and footer totals of a pipeline report.

**What it represents.** Probability-weighted pipeline value, ticket counts, and concentration views
(top-N, deals above a threshold), grouped by product or stage.

**Implementation.** Pure client-side arithmetic over D1 — no new API surface. Verified against the deck:
`amount × standard probability` and `amount × rep-entered probability` reproduce its two value columns
exactly. Keep the two series separately labelled end to end. Grouping key, threshold and N are
parameters. Emit the row count behind every aggregate so a truncated walk can never be mistaken for a
complete total.

*Depends on:* D1.

### D3 — Staleness and recency flags

**UI surface.** Conditional formatting on a pipeline report — recency colour bands, and per-stage
"no activity within N days" flags.

**What it represents.** Neglect detection: deals sitting too long in a stage, or relationships with no
recent contact. The *concept* is general; the bands and per-stage day counts are tenant policy.

**Implementation.** Compute days-since-last-touch and days-in-current-stage (the latter already exists in
`get_opportunities`), then classify against **configurable** thresholds. Ship defaults but never
hardcode; Capstone's are recency bands at 14/30/90 days and per-stage limits of 180/90/60/45/30 days
descending through the funnel, keyed by *their* stage names — which is exactly why stage-keyed thresholds
must be configuration.

Note the last-touch input needs per-party activity, i.e. Epic F. Ship D1–D2 without it if F is blocked.

*Depends on:* D1, F1. *Threshold config via:* A5.

---

## Epic E — Activity tags

**In scope** (E1–E2 wave 1, E3–E4 wave 3). Standard Backstop, not Capstone. Currently **zero references**
to activity tags in the service, despite this being how Backstop answers "when did we last discuss
topic Y with account Z" — a workflow already in §2 of the requirements page. Natively supported and cheap.

### E1 — `list_activity_tags`

**UI surface.** The tag picker when logging a meeting, call or note; tag admin.

**What it represents.** The tenant's topic/strategy taxonomy for activities. Universal mechanism, tenant
vocabulary. Also the id lookup every other tag query needs.

**Implementation.** Wrap `GET /activity-tags` (filterable on `name`, sortable on `name`/`viewable`).
Cache like the other reference vocabularies. Small, and unblocks E2–E4.

### E2 — Surface tags on the activity timeline

**UI surface.** Tag chips on each activity in a record's activity feed.

**What it represents.** Which topics a given interaction covered.

**Implementation.** Add `include=activityTags` to the activity-history fetches and add tags to
`TimelineRecord`. Without this, per-topic filtering is impossible at any level.

Note the asymmetry, and document it: `/meeting-or-calls`, `/notes` and `/documents` support tags, but
**`/emails` has no tag support and no includes at all**. Email cannot participate in tag analytics; say so
in tool output rather than letting totals look complete.

*Depends on:* E1.

### E3 — `get_activity_summary` (tag-scoped counts over a window)

**UI surface.** Activity/engagement reporting broken down by tag.

**What it represents.** Where the firm's attention went over a period — which topics dominated
conversations. Capstone's deck renders this as a 90-day bar chart by strategy.

**Implementation.** `filter[activityTagIds]` plus a date window across `/meeting-or-calls`
(`filter[startTimestamp]`), `/notes` and `/documents` (`filter[createdTimestamp]`). Cheap precisely
because it needs no party attribution — counts per tag per period, with optional comparison against a
prior window for trend.

Return counts per activity type as well as totals, state the excluded email stream (E2), and take the
window and tag set as parameters with no default tag list.

*Depends on:* E1, B1.

### E4 — Tag-scoped activity retrieval for a party

**UI surface.** A record's activity feed filtered to one tag.

**What it represents.** "Everything we've discussed with this investor about topic X" — the input to a
topic-specific briefing, and the direct answer to the §2 workflow above.

**Implementation.** `GET /activity-tags/{id}/activities?filter[activityType][eq]=…`, intersected with a
party, returning timeline records that `get_activity_detail` can expand. Generic in both tag and party.

*Depends on:* E1. *Answers Confluence §7 D2 generically.*

---

## Epic F — Engagement statistics

Deck pages 4, 8, 10. **Scope depends on B1's attribution finding.**

### F1 — `get_engagement_stats` (per party)

**UI surface.** A record's activity feed, counted by hand today.

**What it represents.** Relationship health: last contact date, interaction counts by type and period,
days since last touch. Fully general — no tenant vocabulary involved.

**Implementation.** `get_activity_history` already returns the timeline but no counts and no
call-vs-meeting split. Add an aggregation returning last-touch date and counts per activity type per
period, with caller-specified comparison periods (avoid hardcoding "current year vs prior year";
Capstone's deck wants 2026 calls, 2026 meetings and 2025 combined, which is just two windows).

Feeds D3 and H1. Genuinely useful standalone, and cheap because it is party-scoped.

*Depends on:* A1.

### F2 — Firm-wide engagement aggregation

**UI surface.** Management engagement reporting; the weekly meeting calendar.

**What it represents.** Coverage: total activity, distinct parties engaged, split by type, grouped by
representative, plus a forward window for scheduled meetings.

**Implementation.** If B1 shows activities carry no party relationship, this cannot be done from the
activity collections and must instead walk parties with `include=meetingOrCalls,notes,activities` —
expensive, needing caps and caching. Note `/meeting-or-calls` supports a forward `startTimestamp`
filter, so the *upcoming meetings* half is cheap regardless; consider shipping that separately from the
retrospective aggregation.

Coverage-versus-target framing is deliberately excluded: targets are not in Backstop (client question 2).
Return the numerator and let the caller supply any target.

*Depends on:* B1, C2, F1.

### F3 — Frequent contacts per party

**UI surface.** Attendee lists on meeting records.

**What it represents.** Which individuals we actually deal with, as opposed to everyone listed at the
firm — and a useful cross-check on the known stale-contact problem.

**Implementation.** Aggregate `/meeting-or-calls/{id}/attendees` across a party's meetings, ranked by
frequency and recency. Reconcile against `features/data_hygiene/employment.py` so departed contacts are
flagged rather than presented as current.

*Depends on:* F1.

---

## Epic G — Cohort distribution reporting

**Out of product scope** as connector tools. Prefer I1 (`run_report`); C2 is an expensive last
resort. Design notes for an agent projection. Deck page 7.

The **most expensive** epic, because cohort selection cannot be pushed server-side. Scope after I1
if it is ever built.

### G1 — Cohort field distribution and index

**UI surface.** A grouped/summarised report over a filtered party list.

**What it represents.** Two things, both general: the distribution of an ordinal field across a cohort,
and its mean ordinal as a single index — a one-number summary of how far a book has progressed.
Capstone reports this overall and per representative.

**Implementation.** Compose C2 (cohort) + A4 (ordinal parsing) + C3 (rep grouping). Aggregate any
caller-nominated ordinal field over any cohort, with an optional grouping key.

**Report unparseable values explicitly** rather than excluding them silently — the Capstone sandbox
contains live values outside their field's current option list, and dropping them would quietly bias the
index. Also return cohort size and scan coverage.

*Depends on:* C2, A4, C3.

### G2 — Historical field values ("original vs current")

**UI surface.** A record's change history.

**What it represents.** Movement over a period — did this relationship advance or stall.

**Implementation.** `GET /history-events` is the only route, and it is weak: filterable on
`occurredTimestamp` **only**, sortable on `eventType`/`occurredTimestamp`/`subjectBackstopId`/`subjectType`.
So you pull a time window and filter client-side. Assess feasibility at realistic volumes before
committing; a period-start snapshot may be the pragmatic answer instead.

*Blocked on:* client question 3.

---

## Epic H — Party briefing

**H1 is out of product scope** — a Capstone page-11 projection the agent can do from A1/A3. H3 is
optional (person extras by type, not a "LinkedIn" tool). H2/H4 optional. Deck pages 9–11.

### H1 — `get_party_profile`

**UI surface.** The top-of-record summary: tier, statuses, representative, AUM figures, description, and
the strategy/product interest matrix — Capstone: Organization → **Investor Information** tab →
**Investor Status** section.

**What it represents.** The one-screen "who is this investor" briefing. Universal need; every field in it
is tenant-defined.

**Implementation.** A single call assembling standard attributes plus a caller-or-profile-selected set of
custom fields, returning a briefing-shaped projection instead of a field dump. Verified achievable: the
deck's meeting-prep panel reproduces field-for-field from one live org record.

Worth noting for scoping — `contactDescription` on the organization is already populated in the sandbox,
so the company-description requirement may need no external enrichment at all. Include AUM-style money
fields as caller-nominated, since their names and units vary (Capstone stores millions in fields labelled
as such).

*Depends on:* A1, A5. *Enhanced by:* F1.

### H2 — Full account series and peak values

**UI surface.** Party record → **Accounts** tab → the account values chart and its LTD summary.

**What it represents.** Investment history rather than current state: peak balance and when it occurred,
closure dates, lifetime contributions and redemptions. Needed for former-investor briefings.

**Implementation.** `features/accounts/latest.py` takes only the newest point of a dated series. Add
retrieval of the full `/accounts/{id}/values` series with extrema and their dates. Combine with **L1**,
which side-loads these series anyway.

*Depends on:* L1 (recommended).

### H3 — Person enrichment for attendees

**UI surface.** Person record header and its custom fields.

**What it represents.** Who we are actually meeting — title, and any external profile link the tenant
stores.

**Implementation.** Return `jobTitle` plus caller-nominated person custom fields. `HYPER_LINK`-typed
fields are the general mechanism for external profile links (Capstone has one for LinkedIn) — surface by
type and definition, never by hunting for the label "LinkedIn".

*Depends on:* A1.

### H4 — `get_tasks_for_party`

**UI surface.** Tasks/projects associated with a record.

**What it represents.** Open commitments and follow-ups against a relationship.

**Implementation.** `GET /tasks` supports `filter[entityId]` and `filter[entityType]`, so this is small
and well-supported. Include `assignedUser` and due dates.

*Blocked on:* client question 4 — confirm the client's "projects" are Backstop tasks and not an external
tracker.

---

## Epic I — Reports

### I1 — `run_report`

**UI surface.** **Report Center** (saved report names) and **Report Builder** (definitions). A rendered
report exposes its own definition via *View Report and Field Definitions → Show Report Definition*.

**What it represents.** The tenant's own curated reports — the exact artefacts users pull into Excel
today, with their column logic and filters already encoded. Universal mechanism; every tenant's report
names and definitions differ.

**Implementation.** Wrap `/reports`, taking `asOfDate` plus either `reportName` or
`reportDefinition` + `restrictionExpression`. Prefer POST: GET is length-limited and practical only for
report names. Transport is already prepared — `client.py` gives `/reports` a 120s timeout and a 500-row
default page size — there is simply no tool.

Two constraints to encode in the tool contract: a report **must already exist** in Report Builder, so the
agent can run but never author one; and `reportDefinition`/`restrictionExpression` are opaque serialised
blobs that have to be captured from the UI first, so accept them as configuration rather than expecting an
agent to construct them.

**Assess this before scoping C2 and Epic G.** Report Builder's `restrictionExpression` filters on custom
fields server-side, which no REST collection can do. If a tenant's cohorts already exist as reports, this
ticket may replace a whole epic of walk-based querying. It is also the most portable tool in this
document: it adapts to any tenant with zero code change.

*Blocked on:* client question 1.

---

## Epic J — Capital flows

### J1 — `get_capital_flows`

**UI surface.** Account transaction history; subscription and redemption records.

**What it represents.** Actual money movement — realised sales in a period, redemptions, net flows, and
upcoming redemption exposure. Distinct from pipeline (expected) and positions (current balance).

**Implementation.** `/hedge-fund-account-subscriptions` and `/hedge-fund-account-redemptions` both
support `filter[transactionDate]` and sorting, so period queries are direct. Join to account and product
via `include=fundAccount`. Aggregate by product and period.

This is the source for period-to-date sales figures. Note it produces the *actuals* only — targets are
not in Backstop (client question 2) and should be a caller input, not something this tool invents.

*Depends on:* B1.

---

## Epic K — Write-back

**In scope.** Requirement 2 commits to bidirectional support; the connector is currently read-only.
LMR's stated priority is write-back. Client question 8 still decides guardrails (which fields get
first-class parameters, direct save vs draft-for-confirmation) — it does **not** block shipping a
generic write surface.

Default until question 8 is settled: **draft for confirmation**, then write on explicit confirm.
POST/PATCH support already exists in the API and in `BackstopClient`.

- **K1** — log an activity (meeting, call, note) against a party
- **K2** — update opportunity stage and/or amounts
- **K3** — update custom-field values on a party (the generic form of "update Status/Grade"; depends on A1
  for safe field identification and must respect field type and option constraints)
- **K4** — correct contact and account details, addressing the stale-data problem in §2

Because K3 writes to tenant-defined fields, it must validate against the catalog — reject values
outside a dropdown's options, and never write by label match alone.

---

## Epic L — Performance and correctness

### L1 — Side-load account series in `get_product_positions`

**UI surface.** Party or product account listings with balance columns.

**What it represents.** No new semantics — same data, far fewer requests.

**Implementation.** The tool currently issues three sub-requests per account (`/values`,
`/totalInvested`, `/totalRedemptions`) for up to 500 accounts — as many as ~1500 requests per call. All
three are side-loadable on the `/accounts` collection, collapsing this to one paginated walk. Independent
of any dashboard work, worth doing regardless, and it also unlocks H2 / L2.

### L2 — Balances on `get_accounts_for_party`

**UI surface.** Party record → **Accounts** tab, including the balance columns.

**What it represents.** "What does this investor hold, and at what value?" — the party-scoped half of
§4A's balances workflow. Universal.

**Implementation.** `get_accounts_for_party` is listing and status only. Getting money today means
listing accounts, then calling `get_product_positions` per product and filtering to the owner. Side-load
the same series as L1 (`values`, `totalInvested`, `totalRedemptions`) on the party account walk so one
call returns current balance and lifetime totals per account. Missing series stay omitted, never zeroed.

*Depends on:* L1 (same include path). Closes the §4A composition gap.

---

## Suggested sequencing

Matches **Status at a glance**. D, G, H1, A5, C2, F2 are not in these waves.

| Wave | Tickets | Rationale |
| --- | --- | --- |
| 1 | A2, A3, A1, E1, E2, L1, L2 | Make the shipped reads usable: catalog, groups, resolved values, tags on the timeline, party holdings. |
| 2 | K1–K4 | Write-back. Draft-for-confirmation until question 8; K3 needs A1. |
| 3 | E3, E4 | Tag-scoped counts and per-party tagged retrieval (§4D). |
| 4 | B1, then C1, C3, F1, I1, J1, H3, H4 as needed | Optional general primitives. **I1 before any cohort walk.** |

Every ticket follows the existing pattern: `features/<domain>/` (fetch + responses) → thin
`server/tools/` wrapper → add to `registry.py` → `respx` tests with the `connect_user` fixture, respecting
the `features/` ↛ `server/` layering rule enforced by `tests/test_layering.py`.
