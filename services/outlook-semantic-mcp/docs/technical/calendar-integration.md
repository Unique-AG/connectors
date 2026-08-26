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
- Relative ranges: `src/utils/relative-range` + `temporal-polyfill`. `engines.node` is 24, which has no native `Temporal`, so the polyfill is a real dependency rather than a wait for the Node 26 runtime image. Call sites import `{ Temporal } from 'temporal-polyfill'` directly — do not install it on `globalThis`, or the polyfill would shadow native `Temporal` on that image. Weeks start Monday. `endOfDay` uses `add({ days: 1 }).startOfDay().subtract({ milliseconds: 1 })`.
- Absolute `startDateTime` / `endDateTime` must be valid Instants with `Z` or `±HH:MM`.
- Fan-out: `using limit = calendarGraphLimit(userId)` — 5 in-flight, refcounted per user.
- Search filters (attendee includes organizer, subject, category) run inside `fetchEvents`.
- Search metric: `osm_search_calendar_events_duration_seconds` with labels `dateWindow`, `hasAttendeeFilter`, `hasSubjectFilter`, `hasCategoryFilter`.
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

Use `search_calendar_events` with `dateRange.rangeType: relative` and `range: next7Days` (starts now) and `attendee` set to the name or SMTP. The attendee filter matches organizer or attendees after Graph returns the window. Answer with the soonest hit: when, where / join URL, and who else is on it. Widen the range only if that window is empty. Do not use `today` for this question — that window includes the whole mailbox-local day, so it can return a meeting that already happened.

### Create a meeting invite for XY

> Create a 30-minute invite for Alex Rivera tomorrow at 10:00, subject Sync, Teams meeting.

1. Optional: `suggest_meeting_times` or `check_availability` if the time is not already agreed.
2. `create_event` with offset-bearing `startDateTime` / `endDateTime`, `attendees: ["alex@example.com"]`, `isOnlineMeeting: true` if they asked for Teams.
3. The user must confirm. Invitations are sent immediately; there is no draft. If the create is retried, reuse `transactionId`.

Delegated create: `list_calendars`, then pass that mailbox plus its `calendarId`. The confirmation names the destination mailbox.
