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
  name: z.string().describe('Display name of the calendar as shown in Outlook.'),
  ownerEmail: z
    .string()
    .nullable()
    .describe('SMTP address of the calendar owner, or null if Graph omitted it.'),
  ownerName: z
    .string()
    .nullable()
    .describe('Display name of the calendar owner, or null if Graph omitted it.'),
  isOwn: z
    .boolean()
    .describe(
      'True when this calendar belongs to the signed-in user, false when it is shared or delegated.',
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
    .describe('Calendars the signed-in user can access, including own, shared, and delegated.'),
  listNotes: z
    .array(z.string())
    .optional()
    .describe(
      'Notes about calendars that could not be listed, such as a Full Access mailbox that returned 403 or 404. Show these after the list.',
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
      "List Outlook calendars the signed-in user can access: their own, calendars shared with them, and calendars of mailboxes they have Full Access to. Returns owner, whether the calendar is the user's own, whether they can edit it, and whether private items are visible. To list meetings in a time window, use search_calendar_events. Each calendar carries a calendarRef — pass it through unchanged to narrow search_calendar_events or to pick the calendar for create_event, and never display it or take it apart. If listNotes is present, show it after the list — a Full Access mailbox that could not be read is omitted from calendars and explained there. If consentRequired is true, ask the user to reconnect Outlook before using calendar tools.",
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
        calendarRef: { calendarId: calendar.calendarId, mailbox: calendar.mailbox },
        name: calendar.name,
        ownerEmail: calendar.ownerEmail,
        ownerName: calendar.ownerName,
        isOwn: calendar.isOwn,
        canEdit: calendar.canEdit,
        canViewPrivateItems: calendar.canViewPrivateItems,
      })),
    };
  }
}
