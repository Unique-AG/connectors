import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { DateRangeSchema } from '~/utils/relative-range';
import { SearchCalendarEventsQuery } from './search-calendar-events.query';
import { META } from './search-calendar-events-tool.meta';
import { GraphDateTimeSchema } from './utils/calendar-display';
import { CalendarRefSchema } from './utils/calendar-ref.schema';
import { EventRefSchema } from './utils/event-ref.schema';

const FiltersSchema = z.object({
  calendars: z
    .array(CalendarRefSchema)
    .max(50)
    .optional()
    .describe(
      'Narrow the search to specific calendars. Take each calendarRef from list_calendars and pass it through unchanged. Omit to search every calendar the user can access, which is the normal case and needs no list_calendars call first.',
    ),
  mailbox: z
    .string()
    .optional()
    .describe(
      'SMTP address of a mailbox to search. Omit to search every calendar the user can access (own, shared, and Full Access). Do not put the mailbox in subject or attendee text.',
    ),
  attendee: z
    .string()
    .optional()
    .describe(
      'Matched against organizer or attendee email (substring) or name (substring or the same name-similarity used for contacts). Applied after Graph returns the window. Omit rather than guess.',
    ),
  subject: z
    .string()
    .optional()
    .describe(
      'Matched against the event subject with a substring or the same name-similarity used for contacts. Applied after Graph returns the window. Omit rather than guess.',
    ),
  category: z
    .string()
    .optional()
    .describe(
      'Case-insensitive exact match against an Outlook category on the event. Omit rather than guess.',
    ),
});

export const SearchCalendarEventsInputSchema = FiltersSchema.extend({
  dateRange: DateRangeSchema.describe(
    'Time window to search. Prefer rangeType relative with a documented range.',
  ),
});

const AttendeeSchema = z.object({
  name: z.string().nullable().describe('Display name of the attendee, or null if omitted.'),
  email: z.string().nullable().describe('SMTP address of the attendee, or null if omitted.'),
  response: z
    .string()
    .nullable()
    .describe(
      'Attendee response: none, organizer, tentativelyAccepted, accepted, declined, or notResponded.',
    ),
  type: z
    .string()
    .nullable()
    .describe('Attendee type: required, optional, or resource. Null if Graph omitted it.'),
});

const CalendarEventSchema = z.object({
  subject: z.string().nullable().describe('Event subject. Null when Graph omitted or redacted it.'),
  body: z
    .string()
    .describe(
      'Plain-text event body, already converted by Graph. May be truncated; see bodyTruncated.',
    ),
  bodyTruncated: z.boolean().describe('True when body was cut to the per-event character cap.'),
  start: GraphDateTimeSchema.describe('Event start.'),
  end: GraphDateTimeSchema.describe('Event end.'),
  location: z
    .string()
    .nullable()
    .describe('Location display name, or null when the event has no location.'),
  joinUrl: z
    .string()
    .nullable()
    .describe('Online meeting join URL when present. Never construct a Teams URL yourself.'),
  attendees: z
    .array(AttendeeSchema)
    .describe('All attendees with per-person response status. Not capped.'),
  organizerName: z.string().nullable().describe('Organizer display name, or null if omitted.'),
  organizerEmail: z.string().nullable().describe('Organizer SMTP address, or null if omitted.'),
  isCancelled: z.boolean().describe('True when the occurrence or event has been cancelled.'),
  isAllDay: z.boolean().describe('True when the event lasts the whole day.'),
  isPrivate: z
    .boolean()
    .describe('True when sensitivity is private or confidential. Details may already be redacted.'),
  sensitivity: z
    .string()
    .nullable()
    .describe(
      'Graph sensitivity: normal, personal, private, or confidential. Null when Graph omitted it. Private or confidential events may have redacted details.',
    ),
  categories: z.array(z.string()).describe('Outlook categories on the event.'),
  recurrence: z
    .string()
    .nullable()
    .describe('Short human summary of the series pattern, or null for a one-off event.'),
  seriesMasterId: z
    .string()
    .nullable()
    .describe('Internal series master ID for occurrences. Never display to the user.'),
  type: z
    .string()
    .nullable()
    .describe('Graph event type: singleInstance, occurrence, exception, or seriesMaster.'),
  showAs: z
    .string()
    .nullable()
    .describe(
      'Free/busy shown to others: free, tentative, busy, oof, workingElsewhere, or unknown.',
    ),
  webLink: z
    .string()
    .nullable()
    .describe(
      'Outlook web link for this event. The only user-facing URL besides joinUrl. Empty means render the subject as plain text.',
    ),
  calendarName: z.string().describe('Display name of the calendar this event was read from.'),
  eventRef: EventRefSchema.describe('Internal handle for this event. Never display it.'),
});

export const SearchCalendarEventsOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when the search ran. False when Graph access failed before any calendar was queried.',
    ),
  message: z.string().describe('Human-readable summary of the outcome.'),
  events: z
    .array(CalendarEventSchema)
    .optional()
    .describe('Matching events, sorted by start time, capped at 100.'),
  searchNotes: z
    .array(z.string())
    .optional()
    .describe(
      'Notes about dropped calendars, truncated results, or timezone fallback. Display after the results.',
    ),
  resolvedWindow: z
    .object({
      startDateTime: z
        .string()
        .describe('Absolute start sent to Graph, including timezone offset.'),
      endDateTime: z.string().describe('Absolute end sent to Graph, including timezone offset.'),
      timeZone: z
        .string()
        .describe(
          'IANA timezone the window was resolved in, or UTC when the mailbox timezone was unavailable.',
        ),
      serverCurrentDateTime: z
        .string()
        .describe('Server clock in that timezone when the window was resolved, including offset.'),
      interpretation: z
        .string()
        .describe(
          'Human description of the window, e.g. "next week = Mon 2026-08-31 00:00 to Sun 2026-09-06 23:59 (Europe/Zurich)". State this when a relative range was used.',
        ),
    })
    .optional()
    .describe('The calendarView window actually queried.'),
  consentRequired: z
    .boolean()
    .optional()
    .describe(
      'True when calendar scopes have not been granted yet. The user must reconnect Outlook before calendar tools will work.',
    ),
});

@Injectable()
export class SearchCalendarEventsTool {
  public constructor(private readonly searchCalendarEventsQuery: SearchCalendarEventsQuery) {}

  @Tool({
    name: 'search_calendar_events',
    title: 'Search Calendar Events',
    description:
      'Search Outlook calendar events in a time window across the signed-in user\'s calendars, including shared calendars and Full Access mailboxes. Prefer dateRange.rangeType=relative with a documented range (today, tomorrow, thisWeek, nextWeek, lastMonth, next7Days, …); weeks start Monday. Vague phrasing ("soon", "recently") should use the closest documented range. Absolute startDateTime/endDateTime must include a timezone offset — Graph does not reinterpret them via Prefer: outlook.timezone. Each result includes the full plain-text body (possibly truncated — see bodyTruncated); there is no second tool to open an event. eventRef, eventId, calendarId and mailbox are internal — never display them. If searchNotes is present, show it after the results. If a relative range was used, state resolvedWindow.interpretation. If consentRequired is true, ask the user to reconnect Outlook.',
    parameters: SearchCalendarEventsInputSchema,
    outputSchema: SearchCalendarEventsOutputSchema,
    annotations: {
      title: 'Search Calendar Events',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async searchCalendarEvents(
    input: z.infer<typeof SearchCalendarEventsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof SearchCalendarEventsOutputSchema>> {
    const { dateRange, ...filters } = SearchCalendarEventsInputSchema.parse(input);
    return this.searchCalendarEventsQuery.run(extractUserProfileId(request), {
      ...filters,
      ...(dateRange.rangeType === 'relative'
        ? { range: dateRange.range }
        : { startDateTime: dateRange.startDateTime, endDateTime: dateRange.endDateTime }),
    });
  }
}
