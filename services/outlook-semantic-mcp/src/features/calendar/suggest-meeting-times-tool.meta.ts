import { createMeta } from '@unique-ag/mcp-server-module';
import { CALENDAR_TOOL_FORMAT_INFORMATION } from './utils/calendar-tool-format';

export const META = createMeta({
  icon: 'calendar',
  systemPrompt: `Suggest ranked meeting times via Outlook findMeetingTimes.

Prefer dateRange.rangeType "relative" with a future range (today, tomorrow, thisWeek, nextWeek, next7Days). Weeks start Monday. The window must be shorter than 62 days; past-only ranges are rejected and a start that is already past is clamped to now. Default duration is 30 minutes; default activityDomain is work (mailbox working hours). Omit attendees to find slots for the organizer only.

If emptySuggestionsReason is present, tell the user why Graph found no slots and suggest widening the window or relaxing constraints. If suggestionNotes is present, display it after the results. If a relative range was used, state resolvedWindow.interpretation. If consentRequired is true, ask the user to reconnect Outlook. Do not invent slots.`,
  toolFormatInformation: CALENDAR_TOOL_FORMAT_INFORMATION,
});
