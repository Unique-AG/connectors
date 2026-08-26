<!-- confluence-space-key: PUBDOC -->

# Calendar integration

Read and write paths are landed behind `CALENDAR_INTEGRATION`. Calendar is live Graph query-through: no ingest, webhooks, or calendar tables.

## Operator enablement and re-consent

Do this in order. Flipping the runtime flag before Entra has the scope breaks **mail** token refresh (`invalid_grant`).

1. Apply Terraform `outlook-semantic-mcp-entra-application` with `calendar_integration = true` and grant tenant admin consent for `Calendars.ReadWrite.Shared`.
2. Confirm the Entra app lists that delegated permission.
3. Set `CALENDAR_INTEGRATION=enabled` (`mcpConfig.app.calendarIntegration`).
4. Existing connected users must **reconnect Outlook**, unless an Entra admin has already granted the extra scope tenant-wide. `reconnect_inbox` only renews the mail webhook; it does not re-run OAuth. The user has to start a new Outlook connection.
5. If a calendar tool returns `consentRequired: true`, ask the user to reconnect Outlook. Do not send them to `/auth/authorize`.

Write tools (`respond_to_invite`, `create_event`, `update_event`, `cancel_event`) notify other people immediately after `context.elicit()` confirmation. There is no draft state. `cancel_event` notifies attendees; it is not a silent delete.

Shared-mailbox **profiles** never call calendar tools. A logged-in oauth user queries a shared or delegated calendar via `/users/{owner}/…`.

See [Configuration — CALENDAR_INTEGRATION](../operator/configuration.md#CALENDAR_INTEGRATION) and [Permissions](./permissions.md).

## ID namespaces

Graph calendar and event IDs belong to **one mailbox**. An ID read from `/users/{a}/calendars` returns `404 ErrorItemNotFound` under `/users/{b}`, in both directions. Verified against live Graph on 2026-08-25: a calendar shared from another mailbox read back as `200` under the caller and `404 ErrorItemNotFound` under its owner.

So the mailbox is **provenance**, not a property of the calendar: it is whichever list the ID came out of. `list_calendars` reads two lists and records which one produced each row.

| How the user reaches the calendar | Listed from | `mailbox` | IDs are valid on |
| --- | --- | --- | --- |
| Their own calendars | `/users/{caller}/calendars` | caller SMTP | `/users/{caller}/calendars/{calendarId}/…` |
| A calendar somebody shared with them (they accepted the invitation) | `/users/{caller}/calendars` | **caller SMTP** | `/users/{caller}/calendars/{calendarId}/…` |
| A mailbox they have Full Access to | `/users/{owner}/calendars` | owner SMTP | `/users/{owner}/calendars/{calendarId}/…` |

Note row two. A shared calendar is owned by somebody else but **stored in the caller's mailbox**, so `mailbox` is the caller while `ownerEmail` is the owner. Those two fields answer different questions and must not be conflated:

- `mailbox` — routing. Where the ID resolves. Never displayed.
- `ownerEmail` / `ownerName` — display and filtering. Who it belongs to.

Never infer `mailbox` from the payload. Graph sets `isTallyingResponses: true` on a shared calendar, and treating that as "this is the owner's primary calendar" is what previously routed shared calendars to a 404.

Search and writes always use `/users/{email}/…` (never `/me/calendars`) and send `Prefer: IdType="ImmutableId"` so IDs stay in one namespace.

Rules:

- `calendarRef` (from `list_calendars`) and `eventRef` (from `search_calendar_events`) are opaque handles that pair an ID with its mailbox. Pass them through unchanged; never assemble one from parts.
- Do not display `calendarRef`, `eventRef`, `calendarId`, `eventId`, or `mailbox`.
- Path segments for those IDs are `encodeURIComponent`'d so a slash in a Graph ID cannot leave its segment.

## Contracts

- Tools call queries for reads and commands for writes. Query/command I/O is TypeScript interfaces. Zod + `.describe()` only on tool I/O. `@Tool({ parameters })` is a ZodObject.
- Relative ranges: `src/utils/relative-range` + `temporal-polyfill`. `engines.node` and the `deploy/Dockerfile` image are both Node 26, which has native `Temporal`, but CI runs Node 22, so the polyfill stays a real dependency. Call sites import `{ Temporal } from 'temporal-polyfill'` directly and nothing installs it on `globalThis` — that keeps tests and production on the same implementation instead of shadowing native `Temporal` under test only. Weeks start Monday. `endOfDay` uses `add({ days: 1 }).startOfDay().subtract({ milliseconds: 1 })`.
- Absolute `startDateTime` / `endDateTime` must be valid Instants with `Z` or `±HH:MM`.
- Fan-out: `using limit = calendarGraphLimit(userId)` — 5 in-flight, refcounted per user.
- `list_calendars` unions `/users/{caller}/calendars` with `/users/{owner}/calendars` per Full Access owner. Those owners come from `GetFullAccessMailboxesQuery`, so `DELEGATED_ACCESS_SCAN=disabled` leaves only the caller's own and directly-shared calendars — `listNotes` says so rather than returning a short list as complete.

### Why calendar reads the delegated-access table at all

The two grants are separate in Exchange, and the two sources here mirror that:

| Source | Covers | Path |
|---|---|---|
| `/users/{caller}/calendars` | the caller's own calendars, plus calendars shared with them that they accepted | caller's mailbox |
| Full Access owners from `GetFullAccessMailboxesQuery` | mailboxes the caller holds Exchange "Read and manage (Full Access)" on | each owner's mailbox |

**Verified against live Exchange on 2026-08-26.** A delegate holding Full Access on a mailbox whose calendar had *never* been shared still reads `GET /users/{owner}/calendars` successfully, and that mailbox's calendar does **not** appear in the delegate's own `/users/{caller}/calendars`. So Full Access is a mailbox-wide grant that includes the calendar, and neither source subsumes the other — the union is required. This corrects the design doc, which asserted the mail table "cannot be reused for calendar"; its actual objection was that the table *under-reports* by missing calendar-only sharees, and that half is covered by the first source.

The table is used **only as a list of candidate mailboxes to ask Graph about**. Every candidate is still probed, and a 403/404 drops it with a note, so a stale or over-broad row cannot grant calendar access that does not exist.

`GetFullAccessMailboxesQuery` exists rather than reusing `GetFullDelegatedAccessQuery` because the latter inner-joins `directories`, which holds *mail folders*. That join would hide a mailbox's calendar whenever mail sync had not yet populated the owner — mail bookkeeping deciding calendar visibility. Its caller needs `msGraphDirectoryIds` for KQL scoping; calendar needs only the address.
- Search metric: `osm_search_calendar_events_duration_seconds` with labels `dateWindow`, `hasAttendeeFilter`, `hasSubjectFilter`, `hasCategoryFilter`.

### Which search filters Graph evaluates

`calendarView` documents only "some of the OData query parameters", so the split is deliberate and each half is verified by `buildEventGraphFilter` plus `matchesFilters`.

| Filter | Where | Why |
|---|---|---|
| `categories` | Graph — `categories/any(c:c eq '…')`, first value only | `calendarView` accepts one category comparison. One clause is still correct narrowing, not a partial answer: events carrying every requested category are a subset of those carrying the first, and `matchesFilters` requires all of them. |
| `subject.startsWith` | Graph — `startswith(subject,'…')` | Supported. |
| `subject.contains` | in-process | `contains(subject, …)` is not supported on `calendarView`, and `$search` is documented on neither `calendarView` nor `/events`. `startswith` cannot stand in: it would drop real matches. |
| `attendees` | in-process | `attendees` is a collection of complex types; Graph documents no lambda filter for it. Exact address match, organizer counted as present. |
| window | Graph — `startDateTime` / `endDateTime` | Required parameters. The Graph JS SDK does not encode query values, so `+` in an offset is percent-encoded (`%2B`) before it is sent; otherwise Graph receives a space and rejects `StartDateTime`. `resolvedWindow` still reports the unencoded Instant. |

**`attendees` and `categories` are AND filters.** Narrowing a calendar means every named person or category has to be on the event; a caller who wants either searches twice. Both are case-insensitive, and `attendees` compares whole addresses — there is no substring or name-similarity tier, so a name has to be resolved through `lookup_contacts` first.

**What the split means for the model, and why the prompts say it.** Results are capped (`MAX_EVENTS`, plus `MAX_CALENDAR_VIEW_PAGES` per calendar), so where a filter runs relative to that cap decides what an empty result proves. Graph-side filters narrow *before* the cap, so everything returned is a real match and `searchNotes` reports when more exist. In-process filters run *after* it, on what Graph already returned, so they can find nothing while matching events sit outside the fetched set. The tool description, the field `.describe()` strings, `_meta.systemPrompt` and `CALENDAR_INSTRUCTIONS` all state this, and all instruct the model to resolve an address or category with the user rather than guessing one — a wrong `attendees` value returns an empty result indistinguishable from a free calendar.

Two invariants hold this together:

- **Everything pushed to Graph is re-checked in-process.** The `$filter` is an optimisation, never the source of truth. That is what makes the 400 fallback safe: if Graph rejects a filter it does not support, `fetchEvents` re-reads the window without it and `matchesFilters` still produces the same events.
- **Values are escaped, not interpolated.** OData doubles a single quote inside a string literal. Subject and category text comes from tool input, so `buildEventGraphFilter` is a boundary in the same sense as `SmtpAddressSchema`.

`$orderby=start/dateTime` is sent so paging can stop as soon as `MAX_EVENTS` is held for a calendar, instead of draining five pages per calendar to sort in memory. Note that `$orderby` on `calendarView` is documented ambiguously and the 2026-08-25 probes could not confirm it live (every calendar endpoint returned 403 for want of `Calendars.ReadWrite.Shared`) — despite what the message on `6d9f998e` claims. If Graph ignores it the cap still holds; the result is then an arbitrary `MAX_EVENTS` from the window rather than the earliest, which is what the `searchNotes` cap message reports. Worth confirming once a calendar-scoped token exists.
- Other calendar tools: `osm_calendar_operation_duration_seconds` (same second buckets), labelled by `operation` (`list_calendars`, `check_availability`, `suggest_meeting_times`, `create_event`, `update_event`, `cancel_event`, `respond_to_invite`) and `status`. Recovered Graph failures add `errorType` (`consent`, `not_found`, `permission`, `invalid`, `too_many_entries`, `other`). Availability and suggest also label `dateWindow`. Duration is measured on the query/command, not including elicit wait.
- `check_availability` POSTs `/users/{email}/calendar/getSchedule`. Cap 20 addresses and windows shorter than 62 days. Decode `availabilityView` into non-free `busyBlocks`; redact `items` when `isPrivate`; error 5006 is a narrow-the-range message.
- `suggest_meeting_times` POSTs `/users/{email}/findMeetingTimes`. Default duration 30 minutes and `activityDomain` work. Surface `emptySuggestionsReason` instead of inventing slots.
- `create_event` POSTs after elicit, with `transactionId` (≤ 32 chars). If `calendarId` is omitted it GETs `/users/{email}/calendar`. All-day events are not supported yet.
- `update_event` / `cancel_event` GET the event and calendar first so elicit can name the calendar by owner (never `mailbox`) and, for `occurrence` / `exception`, let the user pick this occurrence vs the whole series. Then PATCH `/events/{id}` or POST `/events/{id}/cancel`.
- `respond_to_invite` GET the event first so elicit can name the invitation (title, when, organizer) before the response is sent.
- 403 on the caller mailbox maps to `consentRequired`. 404/400 map to `success: false`.

## Example prompts

These are user prompts. The assistant should use the named tools and never show internal IDs.

### What meetings do I have next week?

> What meetings do I have next week?

Use `search_calendar_events` with `dateRange.rangeType: relative` and `range: nextWeek`. Weeks start Monday. State `resolvedWindow.interpretation` in the answer. Show subject, start/end (with timezone), attendees and their response, location and/or Teams `joinUrl`, and the agenda from `body`. Use `webLink` when present; do not invent Outlook URLs.

### When is my next meeting with XY?

> When is my next meeting with Alex Rivera?

Use `search_calendar_events` with `dateRange.rangeType: relative` and `range: next7Days` (starts now) and `attendees: ['alex.rivera@…']`. `attendees` is an exact address match, not a name search, so resolve the name with `lookup_contacts` first rather than guessing. It matches organizer or attendees after Graph returns the window. Answer with the soonest hit: when, where / join URL, and who else is on it. Widen the range only if that window is empty. Do not use `today` for this question — that window includes the whole mailbox-local day, so it can return a meeting that already happened.

### Create a meeting invite for XY

> Create a 30-minute invite for Alex Rivera tomorrow at 10:00, subject Sync, Teams meeting.

1. Optional: `suggest_meeting_times` or `check_availability` if the time is not already agreed.
2. `create_event` with offset-bearing `startDateTime` / `endDateTime`, `attendees: ["alex@example.com"]`, `isOnlineMeeting: true` if they asked for Teams.
3. The user must confirm. Invitations are sent immediately; there is no draft. If the create is retried, reuse `transactionId`.

Delegated create: `list_calendars`, then pass that mailbox plus its `calendarId`. The confirmation names the destination mailbox.
