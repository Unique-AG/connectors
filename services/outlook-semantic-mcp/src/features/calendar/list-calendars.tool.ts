import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { ListCalendarsQuery } from './list-calendars.query';
import { META } from './list-calendars-tool.meta';
import { ConsentRequiredSchema } from './utils/calendar-output.schema';
import { CalendarRefSchema } from './utils/calendar-ref.schema';

export const ListCalendarsInputSchema = z.object({});

const CalendarSchema = z.object({
  calendarRef: CalendarRefSchema.describe(
    'Internal handle for this calendar. Pass it through unchanged to search_calendar_events or create_event. Never display it.',
  ),
  name: z
    .string()
    .describe(
      'Display name of the calendar as shown in Outlook. Holiday and birthday calendars appear here too; they are not meeting calendars.',
    ),
  ownerEmail: z
    .string()
    .nullable()
    .describe(
      'SMTP address of the calendar owner, or null if Graph omitted it. On a calendar with isOwn true this is the signed-in user — use it in check_availability and suggest_meeting_times attendees when they want to attend.',
    ),
  ownerName: z
    .string()
    .nullable()
    .describe('Display name of the calendar owner, or null if Graph omitted it.'),
  isOwn: z
    .boolean()
    .describe(
      'True when this calendar belongs to the signed-in user, false when it is shared with them.',
    ),
  isDefaultCalendar: z
    .boolean()
    .describe(
      "True when this is the mailbox's primary calendar. Holiday, birthday, and extra calendars are false, but so are calendars shared with the user (isOwn false), which still hold meetings. For search_calendar_events, pass every isDefaultCalendar true calendar and every isOwn false calendar.",
    ),
  canEdit: z
    .boolean()
    .describe('True when the signed-in user can create or modify events on this calendar.'),
  canViewPrivateItems: z
    .boolean()
    .describe(
      'True when the signed-in user can see details of events marked private. When false, private events are returned redacted.',
    ),
});

export const ListCalendarsOutputSchema = z.object({
  success: z
    .boolean()
    .describe('True when the calendar list was retrieved. False when Graph access failed.'),
  message: z.string().describe('Human-readable summary of the outcome.'),
  calendars: z
    .array(CalendarSchema)
    .optional()
    .describe(
      'Calendars the signed-in user can access, including their own and calendars shared with them.',
    ),
  consentRequired: ConsentRequiredSchema.optional(),
});

@Injectable()
export class ListCalendarsTool {
  public constructor(private readonly listCalendarsQuery: ListCalendarsQuery) {}

  @Tool({
    name: 'list_calendars',
    title: 'List Calendars',
    description:
      "List Outlook calendars the signed-in user can access: their own, and calendars shared with them. Returns owner, whether the calendar is the user's own, whether it is the primary (isDefaultCalendar), whether they can edit it, and whether private items are visible. Primary calendars are listed first. The list can include holiday and birthday calendars — skip those by name. Shared calendars have isOwn false and isDefaultCalendar false and still hold meetings. To list meetings in a time window, call this first, then search_calendar_events with every isDefaultCalendar true calendarRef and every isOwn false calendarRef. When the user asks what meetings another person has, or to look in that person's calendar, pick the calendar whose ownerEmail matches them (isOwn false). If none is listed, do not search isOwn true calendars as a substitute — use check_availability for free/busy and say so. Each calendar carries a calendarRef — pass it through unchanged to search_calendar_events or to pick the calendar for create_event, and never display it or take it apart. ownerEmail on a calendar with isOwn true is the signed-in user SMTP: pass it in check_availability or suggest_meeting_times attendees when they want to attend. If consentRequired is true, ask the user to reconnect Outlook before using calendar tools.",
    parameters: ListCalendarsInputSchema,
    outputSchema: ListCalendarsOutputSchema,
    annotations: {
      title: 'List Calendars',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async listCalendars(
    _input: z.infer<typeof ListCalendarsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof ListCalendarsOutputSchema>> {
    const result = await this.listCalendarsQuery.run(extractUserProfileId(request));
    return {
      ...result,
      calendars: result.calendars?.map((calendar) => ({
        calendarRef: { calendarId: calendar.calendarId },
        name: calendar.name,
        ownerEmail: calendar.ownerEmail,
        ownerName: calendar.ownerName,
        isOwn: calendar.isOwn,
        isDefaultCalendar: calendar.isDefaultCalendar,
        canEdit: calendar.canEdit,
        canViewPrivateItems: calendar.canViewPrivateItems,
      })),
    };
  }
}
