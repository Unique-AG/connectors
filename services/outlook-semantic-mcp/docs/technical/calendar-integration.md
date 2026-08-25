# Calendar integration (UN-22274 / UN-23078)

Read path is landed behind `CALENDAR_INTEGRATION`. Writes are not registered yet — do not name them in prompts.

## Contracts

- Tools call queries. Query I/O is TypeScript interfaces. Zod + `.describe()` only on tool I/O. `@Tool({ parameters })` is a ZodObject.
- Graph calendar paths are always `/users/{email}/…`, never `/me/calendars`. The caller is the oauth user.
- Relative ranges: `src/utils/relative-range` + `temporal-polyfill`. Weeks start Monday. `endOfDay` uses `add({ days: 1 }).startOfDay().subtract({ milliseconds: 1 })`.
- Absolute `startDateTime` / `endDateTime` must include `Z` or `±HH:MM`.
- Fan-out: `using limit = calendarGraphLimit(userId)` — 5 in-flight, refcounted per user. Concurrency, not a cap on calendars queried.
- Search filters (attendee includes organizer, subject, category) run inside `fetchEvents`.
- Metric: `osm_search_calendar_events_duration_seconds` with labels `dateWindow`, `hasAttendeeFilter`, `hasSubjectFilter`, `hasCategoryFilter`. Duration buckets match other `*_duration_seconds` histograms.
- `check_availability` POSTs `/users/{email}/calendar/getSchedule`. Cap 20 addresses and windows ≥ 62 days in the tool Zod schema; the query asserts those invariants. Decode `availabilityView` into non-free `busyBlocks`; redact `items` when `isPrivate`; error 5006 is a narrow-the-range message.
- `suggest_meeting_times` POSTs `/users/{email}/findMeetingTimes`. Default duration 30 minutes and `activityDomain` work. Zod rejects past-only and ≥ 62-day ranges; the query clamps a start that is already past to now. Surface `emptySuggestionsReason` instead of inventing slots.

## Probes

`docs/json/calendar-probes/` is GET-only. Tokens go in gitignored `.env`. Live calendar Graph is 403 until a token with `Calendars.ReadWrite.Shared` is provided.

## Still to build

1. `respond_to_invite` with `context.elicit()` (not `/auth/authorize`)
2. `create_event` / `update_event` / `cancel_event`
3. Operator + technical docs wrap-up
