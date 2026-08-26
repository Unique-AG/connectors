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

export const CALENDAR_INSTRUCTIONS = `
## Outlook Calendar
- Use \`list_calendars\` to see the user's own calendars, calendars shared with them, and calendars of mailboxes they have Full Access to. Pass each \`calendarRef\` to \`search_calendar_events\` as \`calendars\`. The list can include holiday and birthday calendars; for meetings between people, pass only those people's actual calendars, not the holiday ones.
- Use \`search_calendar_events\` for meetings in a time window. Call \`list_calendars\` first; do not scope the search by mailbox address. Prefer \`dateRange\` with \`rangeType: relative\` (\`today\`, \`thisWeek\`, \`nextWeek\`, \`lastMonth\`, \`next7Days\`). Weeks start Monday. State \`resolvedWindow.interpretation\` in the answer.
- Its filters are not equal, and results are capped. \`subject.startsWith\` and the first \`categories\` value are sent to Microsoft Graph, so they narrow before the cap. \`subject.contains\`, \`attendees\` and any further category are applied afterwards, on the events Graph returned — so an empty result there means "nothing matched in what came back", not "no such meeting exists". Say so when \`searchNotes\` reports capped results, and offer a narrower window.
- \`attendees\` is an exact address match, and \`attendees\` and \`categories\` both require every listed value to be present. Resolve a name with \`lookup_contacts\` or ask the user before filtering; never invent an address, a category, or a subject fragment.
- Use \`check_availability\` for free/busy of people, DLs, or rooms. At most 20 addresses; the window must be shorter than 62 days. Subject and location on items appear only with detail-level permission; private items are redacted.
- Use \`suggest_meeting_times\` to rank free slots for the organizer and optional attendees. Default duration is 30 minutes and activityDomain is work. If \`emptySuggestionsReason\` is present, explain it instead of inventing times.
- Use \`respond_to_invite\` to accept, tentatively accept, or decline. Pass \`eventRef\` from \`search_calendar_events\` unchanged. The user must confirm before the organizer is notified.
- Use \`create_event\` to create a meeting. There is no draft — invitations are sent immediately after the user confirms. Reuse \`transactionId\` if the create is retried.
- Use \`update_event\` to change an existing meeting. Pass \`eventRef\` unchanged. For a recurring meeting the user chooses this occurrence or the whole series. Attendees are notified immediately.
- Use \`cancel_event\` to cancel a meeting (notifies attendees). Do not treat it as a silent delete. Pass \`eventRef\` unchanged. Only the organizer can cancel. For a recurring meeting the user chooses this occurrence or the whole series.
- \`calendarId\`, \`eventId\`, \`mailbox\` and \`eventRef\` are internal identifiers. Never show them to the user.
- The search result already contains the full meeting body. There is no second tool to open an event.
`;

export function buildServerInstructions(): string {
  const backend = isMicrosoftGraphBackend()
    ? MICROSOFT_GRAPH_INSTRUCTIONS
    : MICROSOFT_GRAPH_AND_UNIQUE_INSTRUCTIONS;
  return isCalendarEnabled() ? `${backend}\n${CALENDAR_INSTRUCTIONS}` : backend;
}
