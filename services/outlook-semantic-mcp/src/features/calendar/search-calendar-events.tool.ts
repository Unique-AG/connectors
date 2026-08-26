import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { DateRangeSchema } from '~/utils/relative-range';
import { SearchCalendarEventsQuery } from './search-calendar-events.query';
import { META } from './search-calendar-events-tool.meta';
import {
  ConsentRequiredSchema,
  EventDateTimeSchema,
  ResolvedWindowSchema,
} from './utils/calendar-output.schema';
import { CalendarRefSchema } from './utils/calendar-ref.schema';
import { EventRefSchema } from './utils/event-ref.schema';
import { smtpAddress } from './utils/smtp-address.schema';

const SubjectFilterSchema = z
  .union([
    z.strictObject({
      startsWith: z
        .string()
        .trim()
        .min(1)
        .describe(
          'How the subject begins. Graph applies this before results are capped, so prefer it whenever you actually know the start of the title, e.g. "Weekly" for "Weekly Sales Review". A wrong prefix excludes the event outright, so do not guess one just to reach the server-side path.',
        ),
    }),
    z.strictObject({
      contains: z
        .string()
        .trim()
        .min(1)
        .describe(
          'A word or phrase anywhere in the subject. Graph cannot evaluate this, so it is applied after results are capped rather than before: on a wide window it sees fewer events than startsWith would, and an empty result does not prove the meeting does not exist.',
        ),
    }),
  ])
  .describe(
    'How to match the event subject. Supply exactly one of startsWith or contains, never both. Both are case-insensitive.',
  );

const FiltersSchema = z.object({
  attendees: z
    .array(smtpAddress('SMTP address that must be on the event, as organizer or as an attendee.'))
    .max(10)
    .optional()
    .describe(
      'Every address listed must be on the event for it to match, so use one address for "meetings with X" and several only for "meetings with X and Y together". Exact whole-address match, case-insensitive — this is not a name search, so resolve a name with lookup_contacts or ask the user rather than guessing an address, since a wrong address returns an empty result that looks like a free calendar. Graph cannot filter on attendees, so this is applied after results are capped: an empty result does not prove the meeting does not exist.',
    ),
  subject: SubjectFilterSchema.optional().describe(
    'Match on the event subject. Omit rather than guess.',
  ),
  categories: z
    .array(
      z
        .string()
        .trim()
        .min(1)
        .describe('Outlook category name that must be on the event. Case-insensitive exact match.'),
    )
    .max(10)
    .optional()
    .describe(
      'Every category listed must be on the event for it to match. To find events carrying either of two categories, search once per category rather than listing both. Graph applies the first value before results are capped; any further values are checked afterwards. Each must name an existing Outlook category exactly, so omit rather than guessing.',
    ),
});

export const SearchCalendarEventsInputSchema = FiltersSchema.extend({
  calendars: z
    .array(CalendarRefSchema)
    .min(1)
    .max(50)
    .describe(
      'Which calendars to search. Call list_calendars first and pass each calendarRef through unchanged. The list can include noise such as holiday or birthday calendars: for meetings between people, pass only those people\'s actual calendars (typically isOwn, or a named person\'s Calendar), not holiday calendars. Pass every meeting calendarRef from the list only when the user wants all meeting calendars. Never assemble a calendarRef yourself and never use a mailbox address to choose calendars.',
    ),
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
  start: EventDateTimeSchema.describe('Event start.'),
  end: EventDateTimeSchema.describe('Event end.'),
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
      'Notes about dropped calendars, capped results, or timezone fallback. Display after the results.',
    ),
  resolvedWindow: ResolvedWindowSchema.optional().describe(
    'The calendarView window actually queried.',
  ),
  consentRequired: ConsentRequiredSchema.optional(),
});

@Injectable()
export class SearchCalendarEventsTool {
  public constructor(private readonly searchCalendarEventsQuery: SearchCalendarEventsQuery) {}

  @Tool({
    name: 'search_calendar_events',
    title: 'Search Calendar Events',
    description:
      'Search Outlook calendar events in a time window. Call list_calendars first and pass those calendarRef values as calendars — that is how you choose among the signed-in user\'s own, shared, and Full Access calendars. Do not scope by mailbox address. list_calendars can return noise such as holiday calendars: for meetings between people, pass only those people\'s actual calendars, not holiday or birthday calendars. Pass every meeting calendarRef from the list only when the user wants all of them.\n\nTime window: prefer dateRange.rangeType=relative with a documented range (today, tomorrow, thisWeek, nextWeek, lastMonth, next7Days, …); weeks start Monday. Vague phrasing ("soon", "recently") should use the closest documented range. Absolute startDateTime/endDateTime must include a timezone offset — Graph does not reinterpret them via Prefer: outlook.timezone.\n\nWhere each filter runs, because it changes what an empty result means. Results are capped, and the cap is what makes an answer incomplete. subject.startsWith and the first value of categories are sent to Microsoft Graph, so they narrow BEFORE the cap: every event you get back is a real match, and searchNotes tells you when more of the same exist. subject.contains, attendees, and any category after the first are evaluated in this service AFTER the cap, on the events Graph already returned — so they are a convenience, not a guarantee. They can return nothing while matching events sit outside what was fetched.\n\nSo: an empty result from subject.contains or attendees does not prove the meeting does not exist. When searchNotes reports that results were capped, say the answer may be incomplete and offer a narrower window instead of answering "there are no such meetings".\n\nGather what you need before calling, rather than guessing a filter. attendees is an exact whole-address match, not a name search: a partial or wrong address silently returns nothing that reads exactly like an empty calendar. Resolve a name with lookup_contacts, or ask the user, first. categories must match an existing Outlook category exactly. Choosing subject.startsWith over subject.contains has to be a fact about the title, not a guess made to reach the server-side path — a wrong prefix excludes the event entirely. attendees and categories are AND filters: every value listed must be on the event, so search once per value when the user means either. If you cannot build a filter confidently, either ask the user or search on the time window alone and read the results.\n\nEach result includes the full plain-text body (possibly truncated — see bodyTruncated); there is no second tool to open an event. eventRef, eventId, calendarId and mailbox are internal — never display them. If searchNotes is present, show it after the results. If a relative range was used, state resolvedWindow.interpretation. If consentRequired is true, ask the user to reconnect Outlook.',
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
