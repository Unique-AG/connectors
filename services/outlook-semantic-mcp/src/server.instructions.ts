import { isCalendarEnabled, isMicrosoftGraphBackend } from '~/utils/backend-config.utils';

const MICROSOFT_GRAPH_INSTRUCTIONS = `
Emails are searched directly via Microsoft Graph KQL —
no ingestion, sync, or knowledge base is involved.
All tools operate directly against the live mailbox.
`;

const MICROSOFT_GRAPH_AND_UNIQUE_INSTRUCTIONS = `
## Tool Selection Guidelines for Outlook MCP

### Inbox Connection
- If the inbox is not connected, suggest the user run \`reconnect_inbox\` before attempting any other operations.

### Search Results and Incomplete Ingestion
- When \`search_emails\` returns a \`syncWarning\` field, relay that warning message to the user so they know results may not reflect all emails.
`;

const CALENDAR_INSTRUCTIONS = `
## Outlook Calendar
- Use \`list_calendars\` to see the user's own calendars, calendars shared with them, and calendars of mailboxes they have Full Access to.
- Use \`search_calendar_events\` for meetings in a time window. Prefer relative ranges (\`today\`, \`thisWeek\`, \`nextWeek\`, \`lastMonth\`, \`next7Days\`). Weeks start Monday. State \`resolvedWindow.interpretation\` in the answer.
- \`calendarId\`, \`eventId\`, \`accessPath\` and \`eventRef\` are internal identifiers. Never show them to the user.
- The search result already contains the full meeting body. There is no second tool to open an event.
`;

export function buildServerInstructions(): string {
  const backend = isMicrosoftGraphBackend()
    ? MICROSOFT_GRAPH_INSTRUCTIONS
    : MICROSOFT_GRAPH_AND_UNIQUE_INSTRUCTIONS;
  return isCalendarEnabled() ? `${backend}\n${CALENDAR_INSTRUCTIONS}` : backend;
}
