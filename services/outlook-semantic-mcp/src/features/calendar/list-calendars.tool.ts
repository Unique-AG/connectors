import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { ListCalendarsQuery, ListCalendarsQueryOutputSchema } from './list-calendars.query';
import { META } from './list-calendars-tool.meta';

const InputSchema = z.object({});

@Injectable()
export class ListCalendarsTool {
  public constructor(private readonly listCalendarsQuery: ListCalendarsQuery) {}

  @Tool({
    name: 'list_calendars',
    title: 'List Calendars',
    description:
      "List Outlook calendars the signed-in user can access: their own, calendars shared with them, and calendars of mailboxes they have Full Access to. Returns owner, whether the calendar is the user's own, whether they can edit it, and whether private items are visible. calendarId and accessPath are internal — do not display them. If consentRequired is true, ask the user to reconnect Outlook before using calendar tools.",
    parameters: InputSchema,
    outputSchema: ListCalendarsQueryOutputSchema,
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
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof ListCalendarsQueryOutputSchema>> {
    return this.listCalendarsQuery.run(extractUserProfileId(request));
  }
}
