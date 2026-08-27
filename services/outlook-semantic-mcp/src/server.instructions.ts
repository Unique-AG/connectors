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
- Use \`list_calendars\` to see the user's own calendars and calendars shared with them. Pass each \`calendarRef\` to \`search_calendar_events\` as \`calendars\`. Primary calendars (\`isDefaultCalendar\` true) are listed first. Holiday and birthday calendars are not meeting calendars — skip them by name. Shared calendars have \`isOwn\` false and often \`isDefaultCalendar\` false; still pass those for meetings between people, together with every primary. \`ownerEmail\` on a calendar with \`isOwn\` true is the signed-in user SMTP — use it in \`check_availability\` and \`suggest_meeting_times\` \`attendees\` when they want to attend.
- When the user asks what meetings another person has, or to look in that person's calendar: \`list_calendars\` first, then pass only the \`calendarRef\` whose \`ownerEmail\` matches them (\`isOwn\` false). A calendar somebody shared with the user is listed under their own account, so \`list_calendars\` is the only way to reach it — never assemble a \`calendarRef\` yourself. If no matching calendar is listed, you cannot read their events: use \`check_availability\` for free/busy and say so. Do not search calendars with \`isOwn\` true and present those results as theirs. \`organizerName\` / \`organizerEmail\` on an event is who created that meeting, not whose calendar you searched. \`attendees\` on \`search_calendar_events\` finds meetings with that person on calendars you can already read; it is not how you open their calendar.
- Use \`search_calendar_events\` for meetings in a time window. Call \`list_calendars\` first and pass its \`calendarRef\` values. Prefer \`dateRange\` with \`rangeType: relative\` (\`today\`, \`thisWeek\`, \`nextWeek\`, \`lastMonth\`, \`next7Days\`). Weeks start Monday. State \`resolvedWindow.interpretation\` in the answer.
- Its filters are not equal, and results are capped. \`subject\` (either \`startsWith\` or \`contains\`) is sent to Microsoft Graph, so it narrows before the cap. \`attendees\` and \`categories\` are applied afterwards, on the events Graph returned — so an empty result there means "nothing matched in what came back", not "no such meeting exists". Say so when \`searchNotes\` reports capped results, and offer a narrower window.
- \`attendees\` is an exact address match, and \`attendees\` and \`categories\` both require every listed value to be present. Resolve a name with \`lookup_contacts\` or ask the user before filtering; never invent an address, a category, or a subject fragment.
- Use \`check_availability\` for free/busy of people, DLs, or rooms. Only \`attendees\` are checked (at most 20). Include the signed-in user in \`attendees\` when they want to attend; get their SMTP from \`list_calendars\` \`ownerEmail\` on a calendar with \`isOwn\` true (prefer \`isDefaultCalendar\` true). The window must be shorter than 62 days. Subject and location on items appear only with detail-level permission; private items are redacted.
- Use \`suggest_meeting_times\` to rank free slots. Always runs as the signed-in user (the organizer). Include them in \`attendees\` when they want to attend; get their SMTP from \`list_calendars\` \`ownerEmail\` on a calendar with \`isOwn\` true (prefer \`isDefaultCalendar\` true). Omit \`attendees\` for organizer-only. Default duration is 30 minutes and activityDomain is work. If \`emptySuggestionsReason\` is present, explain it instead of inventing times.
- Use \`respond_to_invite\` to accept, tentatively accept, or decline. Pass \`eventRef\` from \`search_calendar_events\` unchanged. The user must confirm before the organizer is notified.
- Use \`create_event\` to create a meeting. There is no draft — invitations are sent immediately after the user confirms. Reuse \`transactionId\` if the create is retried. Write \`body\` as HTML, not Markdown: paragraphs, line breaks, bold, italic, lists, and links. Send a fragment with no html/head/body wrappers. Do not include the Teams join section.
- Use \`update_event\` to change an existing meeting. Pass \`eventRef\` unchanged. For a recurring meeting the user chooses this occurrence or the whole series. Attendees are notified immediately. Write \`body\` as HTML the same way as create_event; this tool keeps Microsoft's existing Teams join HTML.
- Use \`cancel_event\` to cancel a meeting (notifies attendees). Do not treat it as a silent delete. Pass \`eventRef\` unchanged. Only the organizer can cancel. For a recurring meeting the user chooses this occurrence or the whole series.
- \`calendarId\`, \`eventId\`, \`calendarRef\` and \`eventRef\` are internal identifiers. Never show them to the user.
- The search result already contains the full plain-text meeting body. There is no second tool to open an event.
- If a calendar tool returns \`consentRequired\` true, ask the user to reconnect Outlook. Do not call \`reconnect_inbox\` and do not send them to /auth/authorize.
`;

export function buildServerInstructions(): string {
  const backend = isMicrosoftGraphBackend()
    ? MICROSOFT_GRAPH_INSTRUCTIONS
    : MICROSOFT_GRAPH_AND_UNIQUE_INSTRUCTIONS;
  return isCalendarEnabled() ? `${backend}\n${CALENDAR_INSTRUCTIONS}` : backend;
}
