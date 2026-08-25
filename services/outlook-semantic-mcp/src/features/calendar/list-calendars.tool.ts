import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import type { AppConfigNamespaced } from '~/config';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { ListCalendarsQuery, ListCalendarsQueryOutputSchema } from './list-calendars.query';
import { META } from './list-calendars-tool.meta';

export const ListCalendarsInputSchema = z.object({});

@Injectable()
export class ListCalendarsTool {
  public constructor(
    private readonly listCalendarsQuery: ListCalendarsQuery,
    private readonly configService: ConfigService<AppConfigNamespaced, true>,
  ) {}

  @Tool({
    name: 'list_calendars',
    title: 'List Calendars',
    description:
      "List Outlook calendars the signed-in user can access, including their own and any shared or delegated calendars. Returns owner, whether the calendar is the user's own, whether they can edit it, and whether private items are visible. Use calendarIds from this result to narrow search_calendar_events. calendarId and accessPath are internal — do not display them. If consentRequired is true, the user must reconnect Outlook before calendar tools will work.",
    parameters: ListCalendarsInputSchema,
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
    _input: z.infer<typeof ListCalendarsInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof ListCalendarsQueryOutputSchema>> {
    const result = await this.listCalendarsQuery.run(extractUserProfileId(request));
    if (result.consentRequired) {
      const selfUrl = this.configService
        .get('app.selfUrl', { infer: true })
        .toString()
        .slice(0, -1);
      await context.elicitUrl({
        elicitationId: crypto.randomUUID(),
        message: result.message,
        url: `${selfUrl}/auth/authorize`,
      });
    }
    return result;
  }
}
