export const CALENDAR_TOOL_FORMAT_INFORMATION = `## Calendar Display Rules
ALWAYS follow these rules when displaying results from calendar tools.

### Format for listing calendars
When listing calendars, use a markdown table with exactly 4 columns: Calendar, Owner, Can edit, Private items.
- **Calendar**: The calendar \`name\`. Add "(your calendar)" when \`isOwn\` is true.
- **Owner**: Display as "Name (email)" when both are present, otherwise the email or name alone.
- **Can edit**: Yes or No from \`canEdit\`.
- **Private items**: "Visible" when \`canViewPrivateItems\` is true, otherwise "Redacted".
- A row with \`isOwn: false\` and \`canEdit: true\` is a delegated or shared calendar the user can schedule on.

| Calendar | Owner | Can edit | Private items |
|----------|-------|----------|---------------|
| {name} | {Name (email)} | Yes/No | Visible/Redacted |

### Format for listing meetings
When listing meetings, use a markdown table with exactly 4 columns: Time, Subject, Attendees, Location.
- **Time**: Start–end in the timezone shown on the event, plus the calendar date. Mark all-day events as "All day".
- **Subject**: The event \`subject\`. If \`webLink\` is present, make the subject a markdown link to \`webLink\`. Never construct or guess a URL. If \`isCancelled\` is true, prefix with "Cancelled: ". If \`isPrivate\` is true and the subject is missing or generic, label it "Private event".
- **Attendees**: Names (or emails) with response in parentheses: accepted / tentative / declined / no response. Include the organizer.
- **Location**: \`location\` text, and if \`joinUrl\` is present append " · [Join](joinUrl)".
- After the table, state \`resolvedWindow.interpretation\` when a relative range was used.
- If \`searchNotes\` is present, display those notes after the table.
- The \`body\` field is the full plain-text agenda — summarise it when the user asked what a meeting is about; do not call another tool for it.

| Time | Subject | Attendees | Location |
|------|---------|-----------|----------|
| {start}–{end} | {subject} | {Name (accepted)} | {location} |

### Identifier rules
- NEVER show raw IDs (\`calendarId\`, \`eventId\`, \`accessPath\`, \`eventRef\`, \`seriesMasterId\`) to the user.
`;
