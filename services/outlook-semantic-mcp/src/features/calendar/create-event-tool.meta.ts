import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Create an Outlook calendar event.

There is no draft state. If attendees are included, invitations are sent immediately after the user confirms. startDateTime and endDateTime must include a timezone offset (Z or ±HH:MM).

Use calendarId from list_calendars when creating on a specific or shared calendar. Pass the same transactionId if this create is retried. Write body as HTML, not Markdown: <p>, <br>, <strong>, <em>, lists, and links. Send a fragment with no html/head/body wrappers. Do not include the Teams join section — Graph adds it when isOnlineMeeting is true. The HTML is sent to Outlook unchanged.

Do not display eventRef, calendarRef, eventId, or calendarId. If consentRequired is true, ask the user to reconnect Outlook.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
