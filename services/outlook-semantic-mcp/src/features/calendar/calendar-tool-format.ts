export const CALENDAR_TOOL_FORMAT_INFORMATION = `## Calendar Display Rules
ALWAYS follow these rules when displaying results from calendar tools.

### Format for listing meetings
When listing meetings, use a markdown table with exactly 4 columns: Time, Subject, Attendees, Location/Join.
- **Time**: Use each event's start and end. Format as "Mon DD, YYYY HH:MM–HH:MM". For all-day events, show the date only and label them all-day.
- **Subject**: If \`webLink\` is non-empty, link the subject to it. Otherwise display the subject as plain text. Never construct or guess Outlook URLs.
- **Attendees**: Show display name or email, and response status (accepted / tentative / declined / not responded). Include the organizer. Do not cap the attendee list.
- **Location/Join**: Prefer the online meeting join URL when present, otherwise the location display name.

| Time | Subject | Attendees | Location/Join |
|------|---------|-----------|---------------|
| {Time} | [{Subject}]({webLink}) | {Name (status)} | {location or join URL} |

### Cancelled and private events
- Cancelled events (\`isCancelled: true\`) must be labelled cancelled. Never present them as if they are still on.
- Private events with redacted details (\`sensitivity\` private/personal and missing subject or attendees) must be labelled as private/redacted. Never invent the missing fields.

### Link and identifier rules
- NEVER show raw IDs (\`calendarId\`, \`eventId\`, \`accessPath\`, \`eventRef\`) to the user.
- NEVER construct or guess calendar URLs. When \`webLink\` is empty, show the subject as plain text.
- Pass \`eventRef\` to write tools verbatim. Do not rebuild it.

### searchNotes and resolved window
- If the response includes \`searchNotes\`, display it after the results.
- When a relative range was used, state \`resolvedWindow.interpretation\` so the user knows which days were queried.

### Writes
- Creating, updating, or cancelling a meeting sends invitations immediately. There is no draft to review. Confirm with the user before calling a write tool.
`;
