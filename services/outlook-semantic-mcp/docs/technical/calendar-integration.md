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

## Probes

`docs/json/calendar-probes/` is GET-only. Tokens go in gitignored `.env`. Live calendar Graph is 403 until a token with `Calendars.ReadWrite.Shared` is provided.

## Still to build

1. `check_availability` — `getSchedule` (max 20 addresses, window &lt; 62 days)
2. `suggest_meeting_times` — `findMeetingTimes`
3. `respond_to_invite` with `context.elicit()` (not `/auth/authorize`)
4. `create_event` / `update_event` / `cancel_event`
5. Operator + technical docs wrap-up
