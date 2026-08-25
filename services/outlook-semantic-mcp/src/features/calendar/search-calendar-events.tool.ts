import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { RelativeRangeSchema } from './relative-range.schema';
import {
  SearchCalendarEventsQuery,
  SearchCalendarEventsQueryOutputSchema,
} from './search-calendar-events.query';
import { META } from './search-calendar-events-tool.meta';

const FiltersSchema = z.object({
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
      'Case-insensitive substring matched against attendee name or email after Graph returns the window. Omit rather than guess.',
    ),
  subject: z
    .string()
    .optional()
    .describe(
      'Case-insensitive substring matched against the event subject after Graph returns the window. Omit rather than guess.',
    ),
  category: z
    .string()
    .optional()
    .describe(
      'Case-insensitive exact match against an Outlook category on the event. Omit rather than guess.',
    ),
});

const InputSchema = FiltersSchema.extend({
  rangeType: z.union([
    z
      .literal('relative')
      .describe(
        'Resolve a named window server-side in the mailbox timezone. Prefer this for "tomorrow", "next week", "last month".',
      ),
    z
      .literal('absolute')
      .describe(
        'Pass an explicit window. startDateTime and endDateTime must include a timezone offset; Graph does not apply Prefer: outlook.timezone to these values. Use relative ranges unless the user gave exact timestamps.',
      ),
  ]),
  range: RelativeRangeSchema.optional().describe(
    'Named window such as today, thisWeek, or next7Days. Required when rangeType is relative. Weeks start Monday.',
  ),
  startDateTime: z
    .string()
    .optional()
    .describe(
      'Inclusive start of an absolute window, e.g. 2026-08-25T00:00:00+02:00. Required when rangeType is absolute. Offset is required; a naive timestamp is interpreted as UTC.',
    ),
  endDateTime: z
    .string()
    .optional()
    .describe(
      'End of an absolute window, e.g. 2026-08-26T00:00:00+02:00. Required when rangeType is absolute. Offset is required.',
    ),
});

@Injectable()
export class SearchCalendarEventsTool {
  public constructor(private readonly searchCalendarEventsQuery: SearchCalendarEventsQuery) {}

  @Tool({
    name: 'search_calendar_events',
    title: 'Search Calendar Events',
    description:
      'Search Outlook calendar events in a time window across the signed-in user\'s calendars, including shared calendars and Full Access mailboxes. Prefer rangeType=relative with a documented range (today, tomorrow, thisWeek, nextWeek, lastMonth, next7Days, …); weeks start Monday. Vague phrasing ("soon", "recently") should use the closest documented range. Absolute startDateTime/endDateTime must include a timezone offset — Graph does not reinterpret them via Prefer: outlook.timezone. Each result includes the full plain-text body (possibly truncated — see bodyTruncated); there is no second tool to open an event. eventRef, eventId, calendarId and accessPath are internal — never display them. If searchNotes is present, show it after the results. If a relative range was used, state resolvedWindow.interpretation. If consentRequired is true, ask the user to reconnect Outlook.',
    parameters: InputSchema,
    outputSchema: SearchCalendarEventsQueryOutputSchema,
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
    input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof SearchCalendarEventsQueryOutputSchema>> {
    const filters = {
      mailbox: input.mailbox,
      attendee: input.attendee,
      subject: input.subject,
      category: input.category,
    };
    if (input.rangeType === 'relative') {
      if (input.range === undefined) {
        return {
          success: false,
          message: 'range is required when rangeType is relative.',
        };
      }
      return this.searchCalendarEventsQuery.run(extractUserProfileId(request), {
        ...filters,
        range: input.range,
      });
    }
    if (input.startDateTime === undefined || input.endDateTime === undefined) {
      return {
        success: false,
        message: 'startDateTime and endDateTime are required when rangeType is absolute.',
      };
    }
    return this.searchCalendarEventsQuery.run(extractUserProfileId(request), {
      ...filters,
      startDateTime: input.startDateTime,
      endDateTime: input.endDateTime,
    });
  }
}
