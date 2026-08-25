import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Lists Outlook calendars the signed-in user can access: their own calendars plus shared and delegated calendars from GET /me/calendars.

Use this when the user asks which calendars they have, who a calendar belongs to, or whether they can edit a calendar. Pass \`calendarId\` values into \`search_calendar_events\` to narrow a search. \`calendarId\` and \`accessPath\` are internal — never display them.

A calendar with \`isOwn: false\` and \`canEdit: true\` is typically a delegated or shared calendar you can create meetings on behalf of the owner. \`canViewPrivateItems: false\` means private events on that calendar will be redacted.

If \`consentRequired\` is true, the user must reconnect Outlook to grant calendar permission. Do not invent calendar data.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
