# Capstone Keystone Dashboard → Backstop source mapping

Worked example: for every number in Capstone's "Sales & IR Keystone Dashboard" deck, where does the
data live in Backstop? **This is not the product specification.** `backstop-mcp` is a general connector
for every Backstop tenant. Capstone field names, stages, tags, and dashboard arithmetic are things an
agent discovers at runtime — they must never be compiled into the connector.

The implementation backlog is [`mcp-tool-tickets.md`](mcp-tool-tickets.md).

Sources:

- `202606_Sales & IR Keystone Dashboard.pdf` (11 pages, 5 dashboard sections)
- Confluence [Backstop MCP Connector — Common Workflows & User Requirements](https://unique-ch.atlassian.net/wiki/spaces/Product/pages/2435088393/Backstop+MCP+Connector+Common+Workflows+User+Requirements)
- Live probing of `fb-rm-lg-26.backstopsolutions.com` (the same tenant the deck was built from)
- `.docs-local/backstop/backstop-api-swagger.json` (1192 paths) and the Backstop REST help-centre PDF exports

Verification status is marked on every row:

- **Verified** — read back off the live tenant, values match the deck
- **Inferred** — the field/endpoint exists and is the only plausible source, but no live value confirmed
- **Unknown** — no Backstop source found; needs a Capstone demo (see §7)

---

## How to read this document

Confluence §4 splits the job. Only §4A is shipped. The deck is mostly §4E (group questions) plus
client-side arithmetic over tenant custom fields.

| Confluence | What it is | Connector status |
| --- | --- | --- |
| **§4A Read / lookup** | One person, org, or product | **Shipped** — see below |
| **§4B Summaries** | Skip the Excel step | Agent skill over data we already pull; `run_report` optional. Blocked on the Britton-summary demo. |
| **§4C Write-back** | Log activity, change stage, update fields | **Not shipped.** In scope for the general MCP. |
| **§4D Outreach** | Campaigns + "tied to an effort" | Campaigns = tenant custom-field groups (agent discovers via catalog). Tags = standard Backstop (missing on the timeline). |
| **§4E Group questions** | Whole-book pipeline, cohorts, tag charts | **Not shipped.** Build *generic* firm-wide primitives, not Capstone dashboard tools. |

### Already shipped (§4A)

Ten tools, all one party or one product at a time. None of them is tenant-specific.

| Workflow | Tool |
| --- | --- |
| Last meeting / call / email / note / document with X | `get_activity_history` + `get_activity_detail` |
| Current balances, invested/redeemed, status **by fund** | `get_product_positions` |
| Which accounts a person/org owns (status only, no money) | `get_accounts_for_party` |
| Emails and locations | `get_person` / `get_organization` with `include=email_addresses,locations` |
| Pipeline / opportunity status for one org | `get_opportunities` |

Also shipped: Party ID resolve on every lookup; `get_people_for_party` (current vs former); `list_custom_fields` (catalog); retired emails and former-employment flags.

Caveats that are still **general** (not Capstone):

- Activity history cannot answer "last time we discussed *topic Y* with X" — tags are unused.
- "What does *this investor* hold, with balances" is two tools glued together (`get_accounts_for_party` has no series).
- Custom-field *values* on a record are a flat dump. Duplicate names (`Status` × 8 on a live org) are unusable until joined to the catalog.

### Remaining product work

Build universal Backstop mechanics. An agent with these can reconstruct Capstone's deck (and any other
tenant's equivalent) without us encoding `Grade`, `CGM`, or RAG bands. Details and tickets:
[`mcp-tool-tickets.md`](mcp-tool-tickets.md).

- Join custom-field values to `definitionId` / tab / group on party reads; fix catalog duplication; list groups so an agent can discover campaigns and "tier" sections
- Surface activity tags on the timeline, then tag-scoped fetch/counts
- Balances on a party's accounts
- Write-back (log activity, patch opportunity, patch custom fields, correct contacts)
- Optional later: firm-wide `GET /opportunities`, `run_report`, engagement counts — generic, not Capstone-named

### Do not build (Capstone-shaped; agent computes)

Do **not** ship tools or parameters named after Capstone vocabulary, and do **not** bake dashboard
arithmetic into the connector:

- `get_pipeline` / Weighted Value / Sales Prob Adj Value / Imminent as built-in concepts
- Focus Groups, Status Index, Original Status
- Gross Sales Target and the 80% coverage target (not in Backstop)
- Hardcoded RAG bands and per-stage day thresholds
- A 17-field "strategy interest" briefing tool
- A `list_campaigns` tool keyed on `Target List`

Capstone's Grade / Status / strategy matrix / campaign groups are custom fields. The agent looks them
up with `list_custom_fields` (and, once shipped, group listing + resolved values) and projects the
briefing itself.

### What the rest of this file is for

§1–5 map the deck field-for-field so we know the data exists — a Capstone worked example, including
live definition ids that **must not** be hardcoded. §6 is the API capability matrix: that part is
tenant-agnostic and still load-bearing. §7 is questions for the Capstone demo. §8 was a
dashboard-reconstruction ticket list; the live backlog is [`mcp-tool-tickets.md`](mcp-tool-tickets.md).

---

## 1. Headline conclusion (Capstone worked example)

The deck is **not** built on data we are missing. With one exception (sales targets), every value in
all five dashboard sections is already in this Backstop tenant, and almost all of it in
**organization- and opportunity-level custom fields** that `backstop-mcp` already retrieves but does
not make usable.

The real gap is shape, not coverage:

1. **Every dashboard is a cross-party aggregate.** All 10 existing tools are party-scoped: resolve one
   person/org/product, then fetch its children. Nothing can answer "all opportunities in stage Project"
   or "all Grade = Focus organizations". Backstop does expose firm-wide collections
   (`/opportunities`, `/organizations`, `/meeting-or-calls`, `/notes`, `/emails`, `/documents`) and we
   wrap none of them — but their filter surface is narrow and uneven, which decides the build order.
   See the capability matrix in §6.3: pipeline and activity-tag analytics are close to a direct read,
   whereas anything selecting a cohort by Grade or Status requires a full collection walk. **Product
   response:** ship generic primitives (resolved custom fields, tags, writes, optionally firm-wide
   opportunities and `run_report`). Do not ship a Capstone pipeline dashboard tool.
2. **Custom field values come back unusable.** `get_organization` returns ~130 entries in
   `regularCustomFieldValues` as a flat list with no tab/group context and no filtering. In the live NJ
   record the name `Status` appears 8 times with 8 different `definitionId`s, `Notes` 6 times,
   `Initial Target List` 7 times. The catalog that disambiguates them (`list_custom_fields`) is a
   separate tool, and joining the two is left to the model. **This is the highest-leverage general
   gap** — it is what lets an agent figure out Capstone (or any other tenant) without a semantic
   profile.
3. **Activity tags are not exposed at all.** The strategy tags that drive the deck's activity analytics
   (`/activity-tags`, `/activity-tags/{id}/activities`) have zero references in the service. Tags are a
   standard Backstop feature, not a Capstone invention.
4. **No derived metrics.** Weighted Value, Sales Prob Adj Value, status indices, days-since-last-touch
   and the RAG colour thresholds are all pure client-side arithmetic over data we already fetch. **Leave
   that arithmetic to the agent** (or a skill), keyed on caller-nominated fields — not connector code.

---

## 2. Where this lives in the Backstop UI

Backstop's custom-field definitions carry `tab_name` and `group_name`, which are literally the tab and
section headings on the record page. That gives an exact click-path without needing to browse:

| Deck content | UI location |
| --- | --- |
| Grade, Status, Investor Status, Investor Type, IR Representative, AUM / HF AUM, all per-strategy statuses, Next Step, Notes, Region, General/HF Consultant, Management Owner, Solutions Lead | Organization record → **Investor Information** tab → **Investor Status** section |
| "New Product Targeting" campaigns (Target List flags + outreach tracking) | Organization record → year tabs **2021 / 2022 / 2023 / 2024 / 2025 / 2026** → one section per campaign, e.g. **Converts - Feb 2026 Targeting**, **CCS**, **CGM**, **Dispersion - Leveraged Share Class**, **Equity Replacement**, **Inverse RV**, **Put Writing**, **RV Tail Hedging**, **Dispersion Capacity Update** |
| Australia focus-group flag | Organization record → **Australia** tab → **Australia Targets** section |
| Probability, Imminent, Estimated Fees, Timing, Product, Proposed AUM, Opportunity Type, Notes, Next Step/Plan to involve Paul/Tom | Opportunity record → **Master Pipeline** tab → **Pipeline Entries** section |
| Event/roadshow attendance, LinkedIn URL | Person record → **2026 Events** tab → sections **GVS - September 2026**, **DRF NY & Virtual - May 2026**, **DRF CA - May 2026**; LinkedIn is an ungrouped person field |
| Accounts grid (Product Name, Account Name, Investor Name, Date Funded, Date Closed) and the "Account Details: Values as of …" chart — the deck's page 10 screenshots are this UI verbatim | Party record → **Accounts** tab, Display = *Grouped by product* |
| Opportunities grid (Opportunity Name, Product, Stage, Expected Investment Date, Amount, The Probability, Days Open) — also a verbatim page 10 screenshot | Party record → **Opportunities** tab, Display = *Grouped by product* |
| The saved reports the dashboards are exported from | **Report Center** (report names) / **Report Builder** (definitions). Per the Backstop help docs, `GET /reports` can only run a report that already exists here — see §6.1 |

---

## 3. Page-by-page source map

### 3.1 Page 3–5 — Overview: Asset Raising / Asset Raising detail

| Deck element | Backstop source | Status |
| --- | --- | --- |
| Product axis (CGM, Dispersion, Tail Hedging, Long Vol, CARS, CATS, CCS, Convert Arb, Solutions) | Opportunity custom field **Product** `8648257`, options exactly `CGM, CARS, CATS, Dispersion, Tail Hedging, Long Vol, Solutions, CER, CCS, Convert Arb` | Verified |
| Pipeline amount | `opportunities.requestedAmount` | Verified |
| Weighted Value | `requestedAmount × opportunities.probability` (standard, stage-defaulted but per-opportunity editable) | Verified |
| Sales Prob Adj Value | `requestedAmount × ` custom field **Probability** `8648265` (PERCENT, rep-entered) | Verified |
| Number of Tickets | count of opportunities | Verified |
| Top 5 / Top 10 / Sum of items > $100m | client-side ranking of the same rows | Verified |
| YTD Gross Sales | subscriptions in the current year, `GET /hedge-fund-account-subscriptions?filter[...]`, joined account → product | Inferred |
| **Gross Sales Target** (CGM 500M, Dispersion 500M, Tail Hedging 250M, Long Vol 500M, CARS 0, CATS 50M, CCS 50M, Convert Arb 100M, Solutions 750M, total 2.7B) | **Not in Backstop.** Product custom fields are only Fee Structure, Domicile, Strategy, Onshore/Offshore, Fund Structure. No `/targets` or `/goals` endpoint exists. Round numbers suggest a management-set annual figure held outside the CRM | Unknown |
| Net Flows / upcoming redemption colour (a "potential to also include") | `/hedge-fund-account-redemptions`, `/hedge-fund-account-transactions` | Inferred |
| "Imminent" split of the YTD + Pipeline column | Opportunity custom field **Imminent** `10050431` (DROPDOWN Yes/No) — already exists, just unsurfaced | Verified |

The **Weighted Value** formula was confirmed against a live record: NJ Division of Investment –
Tail Hedging has `requested_amount` 500,000,000 and `probability` 0.15, and the deck's Pipeline Details
row shows Weighted Value 75,000,000. The two probability sources are genuinely different numbers on the
same opportunity and must not be conflated.

### 3.2 Page 6 — Pipeline Details

Table columns, left to right:

| Column | Backstop source | Status |
| --- | --- | --- |
| Representative | organization `representative` relationship → `system-users` | Verified (NJ → Madison O'Connell, matches deck) |
| Company Name | organization `name` | Verified |
| Grade | org custom field **Grade** `8646227`; options `Focus, Super League, Core, Other` | Verified |
| Status | org custom field **Status** `8646237`; options `6 - Cross Sell 2, 5 - Cross Sell 1, 4 - Client, 3 - IDD/ODD, 2 - Project, 1 - Dialogue, 0 - No Dialogue, 0 - Dead` | Verified |
| Product | opportunity custom field **Product** `8648257` | Verified |
| Stage | `opportunities.stage` via `/opportunity-stages`; live ids `42478` Prospect, `42480` Project, `42482` IDD, `96018` Closed, plus Client Approval / Execution | Verified |
| Expected Investment Date | standard opportunity attribute | Verified |
| Amount | `requestedAmount` | Verified |
| Weighted Value / Sales Prob Adj Value | derived, see §3.1 | Verified |
| Days in Current Stage | already computed by `get_opportunities` | Verified |
| Last Call/Meeting in Year | latest meeting-or-call date for the org | Verified (source exists; not currently aggregatable firm-wide) |
| Probability, Imminent flag (the deck's "Update to Add") | custom fields `8648265` and `10050431` — **both already exist in Backstop**; this is purely a surfacing task | Verified |

Conditional formatting to reproduce:

- Last Call/Meeting: `< 14 days` green, `14–30` purple, `31–90` yellow, `> 90` red, none red
- Days in Current Stage flags red when there has been no activity within: Prospect 180d, Project 90d,
  IDD 60d, Client Approval 45d, Execution 30d

### 3.3 Page 7 — Focus Group Details

| Deck element | Backstop source | Status |
| --- | --- | --- |
| Focus book membership ("TOP 100", Focus Groups Details grid) | org custom field **Grade** `8646227` = `Focus` | Verified |
| "Super League" cohort | **Grade** = `Super League` | Verified |
| Current Status | org custom field **Status** `8646237` | Verified |
| Status Index (Original 1.98 / Current 1.87), and by-representative breakdown | mean of the numeric prefix of **Status** across the cohort, grouped by `representative` | Verified (formula), derived |
| **Original Status** | **Not directly available.** `Status` is not a time-series field (`is_time_series = false`), so there is no stored prior value. Candidates: (a) `GET /history-events` — a global audit feed, but filterable only on `occurredTimestamp` and sortable only on `eventType / occurredTimestamp / subjectBackstopId / subjectType`, so a window must be pulled and filtered client-side; (b) a period-start snapshot held in the saved report | Unknown |

### 3.4 Page 4 + 8 — Investor Engagement

| Deck element | Backstop source | Status |
| --- | --- | --- |
| "Super League & Focus Calls/Meetings (Annual)" cohort | **Grade** in (`Super League`, `Focus`) | Verified |
| Total Activities, Total Calls/Meetings, Unique Accounts | count over `/meeting-or-calls`, `/notes`, `/emails`, `/documents` firm-wide collections | Inferred |
| Stats by Rep (Total Active Groups, Total Calls/Meetings, Individual Groups Engaged, Groups >2x Calls/Meetings) | same, grouped by organization `representative` | Inferred |
| Weekly Calendar / Occurred vs Upcoming meetings | `/meeting-or-calls` filtered on date, forwards and backwards | Inferred |
| **Activity Tag Profile — 90 days** (CGM 87, Long Vol 39, Dispersion 33, Solutions 30, Tail Hedging 25, Fixed Income RV 14, Convert Arb 14, CARS 8, CATS 7, Co-Invest/Center Book 4) | **`/activity-tags`** and `/activity-tags/{id}/activities?filter[activityType][eq]=…` — exists in the API, **zero references in `backstop-mcp`** | Inferred (highest-value unwrapped endpoint) |
| "In Due Diligence" count | opportunities in stage IDD | Verified |
| Engagement score / days since last touch / coverage vs target by tier | derived from activity counts + **Grade** as the tier | Verified (inputs), derived |
| "Target: 80%" call/meeting coverage target | **Not in Backstop** — same class of problem as Gross Sales Target | Unknown |

### 3.5 Page 9–11 — Weekly Meeting Summary, Investor Details, Meeting Prep Notes

This is the strongest confirmation in the whole exercise. Reading the live NJ Division of Investment
record back reproduces the page-11 mockup field for field:

| Deck panel (page 11) | Live value | Field |
| --- | --- | --- |
| Rep: Madison O'Connell | Madison O'Connell | `representative` |
| Country: United States Of America | United States Of America | `country` |
| Account Status `2 - Project` | `2 - Project` | **Status** `8646237` |
| Investor Status `Prospect` | `Prospect` | **Investor Status** `261621` |
| Grade `Focus` | `Focus` | **Grade** `8646227` |
| Strategy Interests: CGM `Dialogue` | `Dialogue` | **CGM** `8646229` |
| CATS `2 - Contact Made` | `2 - Contact Made` | **CATS** `8755785` |
| Tail Hedging (Comm.) `Dialogue` | `Dialogue` | **Commingled Tail Hedging** `8653747` |
| Long Vol `2 - Contact Made` | `2 - Contact Made` | **Long Vol** `8716467` |
| Tail Hedging `3 - Pipeline` | `3 - Pipeline` | **Tail Hedging** `8646233` |
| Solutions `3 - Pipeline` | `3 - Pipeline` | **Solutions** `8646235` |

Remaining items on these pages:

| Deck element | Backstop source | Status |
| --- | --- | --- |
| Full strategy-status set | 17 org dropdowns, all in Investor Information → Investor Status: CGM `8646229`, Dispersion `8646231`, Tail Hedging `8646233`, Solutions `8646235`, Long Vol `8716467`, CARS `8729811`, CATS `8755785`, CCS `9861335`, Convert Arb `10075375`, Fixed Income RV `9975829`, Co-Invest/Center Book `9975831`, Portable Alpha `9975833`, Vol Multi-Strat `9975827`, CART `9975825`, RMS `9975823`, Commingled Tail Hedging `8653747`, Execution Services `8653749`. Shared options: `4 - Client, 3 - Pipeline, 2 - Contact Made, 1 - Prospect, 0 - No Interest, 0 - Not Relevant` | Verified |
| Current investments: product, account, date funded, balance; sum by product and firm | `get_accounts_for_party` + `get_product_positions` | Verified (covered today) |
| Former investor: date closed, peak balance and its date | `closedDate` present; **peak balance requires the full `/accounts/{id}/values` series** — current `latest.py` only takes the newest point | Inferred, gap |
| Last Call/Meeting, 2026 call count, 2026 meeting count, 2025 combined | `get_activity_history` returns the timeline but **no counts and no call-vs-meeting split**; `activityType` filtering exists upstream | Verified (source), gap |
| Summary of interaction over past year | `get_activity_history` + `get_activity_detail` | Covered |
| Frequent Contacts (individuals) | `/meeting-or-calls/{id}/attendees`, aggregated per person | Inferred, gap |
| Company description | `contactDescription` on the organization — **already populated in Backstop**, the deck assumed WithIntelligence | Verified |
| AUM / HF AUM | **AUM (in millions)** `1660337` (live: `85000 USD`), **HF AUM (in millions)** `1660339` | Verified |
| Consultants | **General Consultant** `1660341`, **HF Consultant** `1660343` — ENTITY-typed, resolve to organization ids | Verified |
| Investor attendee title / LinkedIn | person `jobTitle` + **LinkedIn** `10111055` (HYPER_LINK) | Verified |
| Meeting objective from calendar invite / strategy tags | `/meeting-or-calls`, `/meeting-or-call-invites`, `/activity-tags` | Inferred |
| "Investor Projects" (`INVPROJ-110`, with Deadline / Owner / Resolved) | Possibly Backstop `/tasks` (global GET + filter exists), but the `INVPROJ-` key format looks like an external tracker | Unknown |
| Asset allocation (eVestment), public company info | External to Backstop by the deck's own annotation | Out of scope |

---

## 4. Answers to the Confluence open questions

Three of the four open questions in §7 can now be closed without a demo.

**D. "How do you flag New Product Targeting? What is a campaign?"** — A campaign is a **custom-field
group on the organization record**, named `<strategy> [+ qualifier]` and filed under a **year tab**. The
flag is a `Target List` / `Initial Target List` dropdown; the rest of the group tracks the outreach.
Live examples: 2026 → `Converts - Feb 2026 Targeting`; 2025 → `CCS`, `Dispersion - Leveraged Share Class`;
2024 → `CGM`, `CCS`, `Equity Replacement`; 2023 → `Dispersion Capacity Update`, `Inverse RV`,
`Equity Replacement`; 2022 → `CARS`, `CATS`, `Put Writing`; 2021 → `RV Tail Hedging`. Typical group
shape: `Initial Target List` (Yes/No, some with `Yes - Melbourne` / `Yes - Sydney` / `Cancelled` /
`No Show`), `Contact Date`, `Sent Presentation`, `What was the response?`, `Call Date`,
`Call Participants`, `Outreach Attempts`, `Follow Up`, `Notes`.

So "surface which investors are flagged under campaign X" = *filter organizations where custom field
definition N = Yes*. That needs a firm-wide organization query and custom-field-value filtering — neither
of which exists today.

**D (second bullet). "What does 'tied to a specific outreach effort' mean?"** — Two distinct things,
and per-party activity fetching covers neither: (a) the campaign custom-field group above, (b) **activity
tags** (`/activity-tags`), which is how the deck's strategy-level activity analytics are built.

**F. "We don't know the source of data for the reports in this PDF."** — Now mapped, §3. The two
genuinely external inputs are **Gross Sales Target per product** and the **80% call/meeting coverage
target**.

**B. "Report generation / summarisation"** — still needs the demo, but §6.1 narrows what to ask.

---

## 5. Data-hygiene findings worth carrying into tool design

1. **Stale dropdown values.** The live NJ record has `CGM = "Dialogue"` and
   `Commingled Tail Hedging = "Dialogue"`, but `Dialogue` is **not** in either field's current option
   list (`4 - Client … 0 - Not Relevant`). Any status-index arithmetic that parses the numeric prefix
   will silently drop these rows. Legacy values must be reported, not discarded.
2. **`list_custom_fields` returns duplicates.** For `organizations` it returned 1028 entries for 257
   unique definition ids — roughly 4× duplication, all with `resource_type = organizations`. Worth a
   look before building anything on top of the catalog.
3. **Name collisions are severe.** Custom field names are only unique within a tab+group. Any tool that
   surfaces values must return `definitionId` plus `tab_name`/`group_name`, or the model cannot tell
   `Status` (Investor Status) from the seven other `Status` fields.
4. **Two different probabilities.** `opportunities.probability` and custom field `Probability`
   `8648265` are both real and both used, for different columns. Name them distinctly.
5. **Stale contacts** — already noted in the Confluence doc; `data_hygiene/employment.py` covers this.

---

## 6. Backstop API capability findings

### 6.1 `/reports` is not a general report API

Per `REST API: Reports Endpoint`, a report must **first be configured in the front end with Report
Builder**. The call then takes `asOfDate` plus either `reportName` (from Report Center) or
`reportDefinition` + `restrictionExpression` (copied from the bottom of a rendered report). GET is
advised only for `reportName` because of URL length limits; POST is the practical route and is what
allows dynamic filters.

Consequences for the connector:

- We cannot author a report from the agent. We can only **run one Capstone has already saved**.
- If Capstone's dashboards are backed by saved reports, running them by name is by far the cheapest
  path to parity — and it inherits their exact column logic, including Gross Sales Target if it is
  embedded there.
- `reportDefinition` + `restrictionExpression` are opaque serialised blobs. Passing them through an MCP
  tool is possible but they must be captured from the UI first.
- Transport is already prepared for this: `client.py` gives `/reports` a 120s timeout and a 500-row
  default page size. There is no tool.

**This is the single highest-leverage thing to establish in the Capstone demo: do these dashboards come
from saved reports, and if so what are their names?**

### 6.2 Firm-wide collections that exist and are unused

Note there is **no** firm-wide `GET /activities` — it exists only as a party sub-collection. Firm-wide
activity aggregation must go through the four typed collections (`/meeting-or-calls`, `/notes`,
`/emails`, `/documents`).

### 6.3 Filter / sort / include capability matrix

This is the constraint that determines how each dashboard has to be built. Backstop's `filterField` is a
**closed enum per collection** — you cannot filter on arbitrary attributes, and you cannot filter on
custom fields at all.

| Collection | Filterable on | Sortable on | Key includes |
| --- | --- | --- | --- |
| `/organizations` | `createdTimestamp`, `modifiedTimestamp`, `name`, `otherId`, `emailDomains`, `matchingDomains`, `entityTypeId` | name, email, id, timestamps, otherId | `representative`, `opportunities`, `meetingOrCalls`, `notes`, `activities`, `emails`, `documents`, `tasks`, `employees`, `aums`, `entityRelationships`, `timeSeriesCustomFieldValues`, `contactEmails`, `contactLocations`, `primaryContact` |
| `/opportunities` | `createdTimestamp`, `modifiedTimestamp`, `otherId`, `entityTypeId`, **`representative.name`** | timestamps, id, otherId | **`investor`**, `representative`, `stage`, `stageHistory`, `product`, `investorType`, `activities`, `meetingOrCalls`, `notes` |
| `/meeting-or-calls` | **`activityTagIds`**, **`startTimestamp`**, `createdTimestamp`, `modifiedTimestamp`, `currentUserOnly` | `startTimestamp`, timestamps, id | `activityTags`, `attendees`, `author`, `invite`, `tasks`, `documents`, `historyEvents` |
| `/notes` | **`activityTagIds`**, `createdTimestamp`, `modifiedTimestamp` | timestamps, id | `activityTags`, `author`, `tasks`, `documents` |
| `/documents` | **`activityTagIds`**, `effectiveDate`, `createdTimestamp`, `modifiedTimestamp` | `effectiveDate`, timestamps, id | `activityTags`, `author` |
| `/emails` | `sentTimestamp`, `fromEmail`, `toEmails`, `ccEmails`, `subject`, `showBodyOnly` | `sentTimestamp`, `subject`, id | — |
| `/accounts` | `product.id`, `product.otherId`, `product.shortName`, `name`, `otherId`, timestamps | name, timestamps, id, otherId | `owner`, `product`, `investorType`, **`values`, `totalInvested`, `totalRedemptions`**, `irrs`, `startingValues`, `highwaterMarks`, `historicalOwners`, `accountTerms`, `analytics` |
| `/hedge-fund-account-subscriptions` (and `-redemptions`) | **`transactionDate`**, `otherId`, timestamps | `transactionDate`, timestamps | `fundAccount`, `shareClass`, `shareSeries`, `transactionType` |
| `/activity-tags` | `name` | `name`, `id`, `viewable` | `activities` |
| `/system-users` | `name`, `lastName` | `name`, `lastName`, `id` | — |
| `/tasks` | **`entityId`, `entityType`**, `dueDate`, timestamps | `dueDate`, timestamps, id | `assignedUser`, `assignedByUser`, `collaborators`, `group` |
| `/products` | `name`, `otherId`, `entityTypeId`, timestamps | name, timestamps | — |
| `/history-events` | `occurredTimestamp` **only** | `eventType`, `occurredTimestamp`, `subjectBackstopId`, `subjectType` | — |

All operators are `eq, neq, gt, ge, lt, le` — there is no `in`, no `like`, no `contains`.

**Five consequences that reshape the build:**

1. **`/opportunities?include=investor,representative,stage,stageHistory,product` gives the whole Pipeline
   Details table in a single paginated walk.** `investor` resolves to the organization, whose custom
   fields (Grade, Status) arrive inline. This is much cheaper than the two-sided join originally planned,
   and `filter[representative.name]` allows per-rep slicing server-side. This is the one relationship-path
   filter in the whole matrix.
2. **Organization cohorts cannot be filtered server-side.** Grade, Status, Investor Status and campaign
   `Target List` flags are custom fields, and `/organizations` has no custom-field filter. Selecting
   "all Grade = Focus" requires a **full collection walk plus client-side filtering**, so Focus Groups
   (§3.3) and campaign targeting (§4 D) are the *most* expensive dashboards to reproduce, not the least.
   This is what makes `/reports` strategically important: Report Builder's `restrictionExpression`
   filters on custom fields server-side, which the REST collections cannot.
3. **Activity tag analytics are the cheapest thing on the list.** `filter[activityTagIds]` combined with
   `filter[startTimestamp]` on `/meeting-or-calls` (plus `activityTagIds` on `/notes` and `/documents`)
   delivers the Activity Tag Profile almost directly. Phase 2 should move ahead of Phase 0/3.
4. **But firm-wide activities cannot be attributed to a party.** The `/meeting-or-calls`, `/notes` and
   `/documents` include lists contain no entity/party/organization relationship. So tag-filtered *counts*
   are easy, while anything needing "which investor was this with" — unique accounts, stats by rep,
   the weekly calendar's client names — has to come from the organization side
   (`/organizations?include=meetingOrCalls,notes,activities`), i.e. a full walk again. Confirm against
   `/resource-metadata` before accepting this, since it is the main cost driver for §3.4.
5. **`get_product_positions` can be made dramatically cheaper.** It currently issues three sub-requests
   per account (`/values`, `/totalInvested`, `/totalRedemptions`) for up to 500 accounts — up to ~1500
   requests. All three are side-loadable on the `/accounts` collection, collapsing this to one paginated
   walk. Independent of the dashboard work; worth doing on its own.

Also note `/emails` is shaped differently from the other three activity collections: no `activityTagIds`,
no `createdTimestamp`, and no includes at all. Email cannot participate in tag-based analytics.

Two caveats on trusting this matrix: the swagger is known to be wrong in both directions on this tenant
(`features/opportunities/fetch.py` records that `filter[isOpen]` returns 400 despite being documented, and
that `sort=` is silently ignored on opportunity sub-collections). Validate every filter against
`/resource-metadata/?filter[resourceType][eq]=<type>` and a live call before building on it.

### 6.4 Other useful discoveries

- `/resource-metadata/?filter[resourceType][eq]=X` enumerates filterable/sortable fields per resource
  type. Use this to confirm which filters actually work before coding, given the swagger's known
  inaccuracy (`filter[isOpen]` 400s, `sort=` silently ignored on opportunity sub-collections).
- `/lov-entries`, `/lov-system-sets`, `/lov-owned-sets` hold list-of-values vocabularies, separate from
  custom-field `select_options`.
- POST-only: `/activity-search` (global text search, needs `searchString`) and `/entity-activities`
  (still entity-scoped, needs `filterName`, `entityId`, `resourceType`).

---

## 7. Questions that still need the Capstone demo

Narrowed to what genuinely cannot be answered from the API:

1. **Are these dashboards backed by saved Backstop reports?** If yes, the report names — this changes
   the whole build strategy (§6.1).
2. **Where does Gross Sales Target per product come from?** Who sets it, where is it stored, how often
   does it change? Same question for the 80% call/meeting coverage target.
3. **How is "Original Status" captured?** A period-start snapshot in the report, a manual second field,
   or reconstructed from history?
4. **What are "Investor Projects" (`INVPROJ-110`)?** Backstop tasks or an external tracker?
5. **Which strategy list is canonical?** The deck's product axis, the opportunity `Product` dropdown
   (which adds `CER`), the 17 org strategy-status fields, and the product `Strategy` dropdown all differ.
6. **Stage weights** — is `opportunities.probability` ever edited away from its stage default, and is the
   default table configurable? Determines whether Weighted Value can be computed or must be read.
7. **The Excel step** (Confluence §7B) — walk through one Britton summary end to end.

---

## 8. Derived work: MCP tool tasks

**Superseded as a product backlog** by [`mcp-tool-tickets.md`](mcp-tool-tickets.md), which drops
Capstone-shaped tools and front-loads writes plus general primitives.

What follows is the original **dashboard-reconstruction** breakdown (cost-to-value given §6.3). Keep
it as a map of which Backstop collections feed which deck pages. Do not treat Phases 1, 4, or 5 as
connector tickets — those are agent projections over generic tools (resolved custom fields, tags,
optionally firm-wide opportunities and `run_report`).

Ordered by **cost-to-value given the §6.3 filter constraints**, not by deck page order. Each phase is
independently shippable. The ordering deliberately front-loads the two dashboards the API supports
natively and defers the ones that require full collection walks.

### Phase 0 — Foundations

- **T0.1 Custom-field values, resolved.** Return custom field values joined to their definitions
  (`definitionId`, `name`, `tab_name`, `group_name`, `field_type`) with selection by tab/group/definition
  id, instead of a flat 130-entry dump. Preserve out-of-vocabulary values (§5.1) explicitly.
  *Affects `features/includes/` and `get_organization` / `get_person`; needed by nearly every dashboard.*
- **T0.2 Fix the `list_custom_fields` duplication** (§5.2).
- **T0.3 Capability probe.** Before anything else, validate the §6.3 matrix against this tenant via
  `/resource-metadata` and live calls — specifically `filter[representative.name]` on `/opportunities`,
  `filter[activityTagIds]` and `filter[startTimestamp]` on `/meeting-or-calls`, and whether any
  party relationship is includable on the activity collections. The swagger is known to be wrong in both
  directions. **This probe determines whether Phase 1 and 2 stand up as written.**
- **T0.4 `system_users` lookup** for representative names and by-rep grouping.

### Phase 1 — Pipeline (deck pages 5–6) — *natively supported, do first*

One paginated walk of `/opportunities?include=investor,representative,stage,stageHistory,product`
produces the entire Pipeline Details table, with Grade and Status arriving inline on the included
organization.

- **T1.1 `get_pipeline`** — rep, company, Grade, Status, product, stage, expected investment date,
  amount, both probabilities, Imminent, days in current stage. Supports server-side rep filtering via
  `filter[representative.name]`; stage/product filtering is client-side.
- **T1.2 Derived pipeline metrics** — Weighted Value, Sales Prob Adj Value, ticket counts, Top-N and
  `> $100m` rollups, per-product summary. Pure computation; keep the two probabilities distinct (§5.4).
- **T1.3 Staleness flags** — the last-call/meeting RAG bands and the per-stage no-activity thresholds
  (§3.2). Thresholds configurable, not hardcoded. Note the last-call/meeting column needs per-org
  activity, which is the Phase 2/4 attribution problem — ship T1.1–T1.2 without it if needed.

### Phase 2 — Activity tag analytics (deck pages 4, 8) — *natively supported*

`filter[activityTagIds]` + `filter[startTimestamp]` make this nearly a direct read.

- **T2.1 `list_activity_tags`** — wrap `/activity-tags` (filterable by `name`); the strategy vocabulary
  and the id lookup every other tag query depends on.
- **T2.2 Activity tags on the timeline** — add tags to `TimelineRecord` via `include=activityTags` so
  per-strategy filtering works at all.
- **T2.3 Tag-scoped activity counts** — the Activity Tag Profile: counts per tag over a date window
  across `/meeting-or-calls`, `/notes`, `/documents`. Cheap, because no party attribution is needed.
  Must state that email is excluded (§6.3).
- **T2.4 `get_activity_tag_activities`** — `/activity-tags/{id}/activities`, for "summarise notes for
  strategy X with investor Y" (deck page 11).

### Phase 3 — Party-attributed engagement (deck pages 4, 8, 10) — *needs the expensive path*

Blocked on T0.3's finding about party attribution. If activities genuinely carry no party relationship,
everything here goes through `/organizations?include=meetingOrCalls,notes,activities` and needs bounded
walks plus caching.

- **T3.1 Per-party engagement stats** — last call/meeting, current-year call count, current-year meeting
  count, prior-year combined, days since last touch. Closes the deck page 10 block and feeds T1.3.
- **T3.2 Firm-wide activity aggregation** — totals, unique accounts, call-vs-meeting split, per-rep
  grouping, and the forward-looking window for the weekly calendar.
- **T3.3 Frequent contacts** — aggregate `/meeting-or-calls/{id}/attendees` per person.

### Phase 4 — Cohort / focus-group reporting (deck page 7) — *most expensive*

No server-side custom-field filtering exists, so every cohort selection is a full `/organizations` walk.
Consider whether T6.1 (`run_report`) supersedes this entirely before building it.

- **T4.1 Organization cohort primitive** — bounded full walk with client-side custom-field predicates
  (Grade, Status, Investor Status, campaign flags), `include=representative`, with caching and explicit
  result caps.
- **T4.2 `get_focus_groups`** — Grade-based cohort with Status, rep, and the status-index aggregation,
  overall and by representative.
- **T4.3 Status-index computation** with explicit handling of legacy values (§5.1).
- **T4.4 Original Status** — blocked on question 3; if history is the answer, wrap `/history-events` with
  the timestamp-window-plus-client-filter caveat.
- **T4.5 Campaign targeting tool** — list campaigns (year tab + group) and the organizations flagged
  under each, with their outreach fields. Directly answers Confluence §7D. Built on T4.1.

### Phase 5 — Investor briefing (deck pages 9–11)

- **T5.1 `get_investor_profile`** — one call returning the page-11 panel: name, Investor Status, Grade,
  Status, representative, all 17 strategy statuses, AUM / HF AUM, consultants, `contactDescription`.
  Mostly a well-shaped projection over T0.1, so it can ship early.
- **T5.2 Peak balance and date** for former investors — needs the full `/accounts/{id}/values` series,
  not just the latest point (§3.5).
- **T5.3 Person enrichment** — job title + LinkedIn (`10111055`) for meeting attendees.
- **T5.4 Investor Projects** — `/tasks` supports `filter[entityId]` + `filter[entityType]`, so if these
  are Backstop tasks this is a small tool. Blocked on question 4.

### Phase 6 — Reports, flows, and performance

- **T6.1 `run_report`** — `/reports` by `reportName`, optionally by `reportDefinition` +
  `restrictionExpression`. Transport is ready; blocked on question 1. **Re-evaluate Phase 4 scope once
  this is known**, since Report Builder can filter custom fields server-side and the REST collections
  cannot (§6.3.2).
- **T6.2 Subscriptions / redemptions** — `filter[transactionDate]` gives YTD Gross Sales and net flows
  directly; join to product via `include=fundAccount`.
- **T6.3 Targets** — blocked on question 2. Likely a configuration input rather than a Backstop read.
- **T6.4 Side-load account series in `get_product_positions`** — replace up to ~1500 per-account
  sub-requests with `include=values,totalInvested,totalRedemptions` on the collection walk (§6.3.5).
  Independent of the dashboards and worth doing regardless.

### Cross-cutting

- Every new tool follows the existing pattern: `features/<domain>/` (fetch + responses) → thin
  `server/tools/` wrapper → add to `registry.py` → `respx` tests with the `connect_user` fixture.
- Firm-wide queries need bounded pagination and result caps; `paginate(parallel=True)` already exists for
  offset fan-out.
- Operators are only `eq, neq, gt, ge, lt, le` — no `in`, no `like`. Multi-value selection means either
  repeated calls or a client-side filter; design tool parameters accordingly.
- Verify each filter against `/resource-metadata` before relying on swagger (§6.3).
