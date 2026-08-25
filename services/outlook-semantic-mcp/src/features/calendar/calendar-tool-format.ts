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

### Identifier rules
- NEVER show raw IDs (\`calendarId\`, \`accessPath\`) to the user.
`;
