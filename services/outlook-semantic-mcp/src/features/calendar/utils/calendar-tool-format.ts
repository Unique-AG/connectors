export const CALENDAR_TOOL_FORMAT_INFORMATION = `## Calendar Display Rules
ALWAYS follow these rules when displaying results from calendar tools.

### Format for listing calendars
When listing calendars, use a markdown table with exactly 4 columns: Calendar, Owner, Can edit, Private items.
- **Calendar**: The calendar \`name\`. Add "(your calendar)" when \`isOwn\` is true. Add "(primary)" when \`isDefaultCalendar\` is true.
- **Owner**: Display as "Name (email)" when both are present, otherwise the email or name alone.
- **Can edit**: Yes or No from \`canEdit\`.
- **Private items**: "Visible" when \`canViewPrivateItems\` is true, otherwise "Redacted".
- A row with \`isOwn: false\` and \`canEdit: true\` is a shared calendar the user can schedule on.
- Primary calendars (\`isDefaultCalendar: true\`) are the account's main meeting calendar. Shared calendars (\`isOwn: false\`) also hold meetings even when \`isDefaultCalendar\` is false. Holiday and birthday calendars are not.

| Calendar | Owner | Can edit | Private items |
|----------|-------|----------|---------------|
| {name} (your calendar, primary) | {Name (email)} | Yes/No | Visible/Redacted |

### Format for listing meetings
When listing meetings, use a markdown table with exactly 4 columns: Time, Subject, Attendees, Location.
- **Time**: Start–end in the timezone shown on the event, plus the calendar date. Mark all-day events as "All day".
- **Subject**: The event \`subject\`. If \`webLink\` is present, make the subject a markdown link to \`webLink\`. Never construct or guess a URL. If \`isCancelled\` is true, prefix with "Cancelled: ". If \`isPrivate\` is true and the subject is missing or generic, label it "Private event".
- **Attendees**: Names (or emails) with response in parentheses: accepted / tentative / declined / no response. Include the organizer.
- **Location**: \`location\` text, and if \`joinUrl\` is present append " · [Join](joinUrl)".
- After the table, state \`resolvedWindow.interpretation\` when a relative range was used.
- If \`searchNotes\` is present, display those notes after the table.
- Never title the table as another person's calendar unless every row came from a calendar whose \`ownerEmail\` matches them (\`isOwn\` false). Events with \`isOwn\` true are the signed-in user's meetings; their \`organizerName\` is often the signed-in user and does not mean you opened the other calendar.
- When results come from more than one calendar, mention \`calendarName\` in the subject cell or in a short line after the table. Do not add a fifth column.
- The \`body\` field is the plain-text agenda Graph already converted. It may be truncated (\`bodyTruncated\`); summarise what is present when the user asked what a meeting is about, and do not call another tool for it.

| Time | Subject | Attendees | Location |
|------|---------|-----------|----------|
| {start}–{end} | {subject} | {Name (accepted)} | {location} |

### Format for availability
When showing free/busy from \`check_availability\`, write one short section per person (\`email\`).
- Summarise \`busyBlocks\` as Time + Status (Tentative / Busy / Out of office / Working elsewhere). Do not list free slots from the bitmap; free time is the complement inside \`workingHours\`.
- When \`items\` have a subject or location, mention them next to the matching time. If \`isPrivate\` is true, label the item "Private" and do not invent a subject.
- After the busy list, state working hours (\`daysOfWeek\`, start–end, timezone) when \`workingHours\` is present.
- After every person, state \`resolvedWindow.interpretation\` when a relative range was used.
- If \`availabilityNotes\` is present, display those notes after the sections.

### Format for suggested meeting times
When showing \`suggest_meeting_times\`, use a markdown table with exactly 4 columns: Time, Confidence, Organizer, Attendees.
- **Time**: Start–end in the timezone shown on the slot.
- **Confidence**: The \`confidence\` percentage.
- **Organizer**: \`organizerAvailability\` (free / tentative / busy).
- **Attendees**: Names or emails with availability in parentheses.
- After the table, state \`suggestionReason\` for the top slot when present.
- If \`emptySuggestionsReason\` is present, explain it and suggest widening the window or relaxing constraints. Do not invent slots.
- After the table, state \`resolvedWindow.interpretation\` when a relative range was used.
- If \`suggestionNotes\` is present, display those notes after the table.

| Time | Confidence | Organizer | Attendees |
|------|------------|-----------|-----------|
| {start}–{end} | {confidence}% | {free} | {email (free)} |

### Identifier rules
- NEVER show raw IDs (\`calendarRef\`, \`eventRef\`, \`calendarId\`, \`eventId\`, \`seriesMasterId\`) to the user.
- \`calendarRef\` and \`eventRef\` are opaque handles. Pass them back exactly as received; never build one from parts.
`;
