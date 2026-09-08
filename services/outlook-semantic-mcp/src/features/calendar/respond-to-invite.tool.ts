import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { RespondToInviteCommand } from './respond-to-invite.command';
import { META } from './respond-to-invite-tool.meta';
import { EVENT_RESPONSES } from './utils/calendar-graph-path';
import { ConsentRequiredSchema } from './utils/calendar-output.schema';
import { EventRefSchema } from './utils/event-ref.schema';

export const RespondToInviteInputSchema = z.object({
  eventRef: EventRefSchema.describe(
    'Internal handle from search_calendar_events. Pass it through unchanged. Never display it.',
  ),
  response: z
    .enum(EVENT_RESPONSES)
    .describe('accept, tentativelyAccept, or decline. This notifies the organizer immediately.'),
  comment: z
    .string()
    .optional()
    .describe('Optional note included with the response to the organizer.'),
});

export const RespondToInviteOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when Graph accepted the response. False when the event was not found or consent is missing.',
    ),
  message: z.string().describe('Human-readable summary of the outcome.'),
  response: z
    .enum(EVENT_RESPONSES)
    .optional()
    .describe('The response that was sent, when success is true.'),
  consentRequired: ConsentRequiredSchema.optional(),
});

@Injectable()
export class RespondToInviteTool {
  public constructor(private readonly respondToInviteCommand: RespondToInviteCommand) {}

  @Tool({
    name: 'respond_to_invite',
    title: 'Respond to Invite',
    description:
      'Accept, tentatively accept, or decline an Outlook meeting invitation. Pass eventRef from search_calendar_events without changing it. The response is sent immediately and notifies the organizer. There is no confirmation prompt and no draft state. If consentRequired is true, ask the user to reconnect Outlook.',
    parameters: RespondToInviteInputSchema,
    outputSchema: RespondToInviteOutputSchema,
    annotations: {
      title: 'Respond to Invite',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async respondToInvite(
    input: z.infer<typeof RespondToInviteInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof RespondToInviteOutputSchema>> {
    return this.respondToInviteCommand.run(extractUserProfileId(request), input);
  }
}
