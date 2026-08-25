import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { ListCalendarsQuery } from './list-calendars.query';
import { META } from './list-calendars-tool.meta';

export const ListCalendarsInputSchema = z.object({});

const CalendarRefSchema = z.object({
  calendarId: z
    .string()
    .describe('Internal Microsoft Graph calendar ID. Never display to the user.'),
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
  accessPath: z
    .enum(['ownMailbox', 'ownerMailbox'])
    .describe('Internal Graph ID namespace. Never display this to the user.'),
});

export const ListCalendarsOutputSchema = z.object({
  success: z
    .boolean()
    .describe('True when the calendar list was retrieved. False when Graph access failed.'),
  message: z.string().describe('Human-readable summary of the outcome.'),
  calendars: z
    .array(CalendarRefSchema)
    .optional()
    .describe('Calendars the signed-in user can access, including own, shared, and delegated.'),
  consentRequired: z
    .boolean()
    .optional()
    .describe(
      'True when calendar scopes have not been granted yet. The user must reconnect Outlook before calendar tools will work.',
    ),
});

@Injectable()
export class ListCalendarsTool {
  public constructor(private readonly listCalendarsQuery: ListCalendarsQuery) {}

  @Tool({
    name: 'list_calendars',
    title: 'List Calendars',
    description:
      "List Outlook calendars the signed-in user can access: their own, calendars shared with them, and calendars of mailboxes they have Full Access to. Returns owner, whether the calendar is the user's own, whether they can edit it, and whether private items are visible. To list meetings in a time window, use search_calendar_events. calendarId and accessPath are internal — do not display them. If consentRequired is true, ask the user to reconnect Outlook before using calendar tools.",
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
    return this.listCalendarsQuery.run(extractUserProfileId(request));
  }
}
