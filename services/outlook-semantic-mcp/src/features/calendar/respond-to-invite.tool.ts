import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { obfuscateEmail } from '~/utils/obfuscate-email';
import { type CalendarEventSnapshot, GetCalendarEventQuery } from './get-calendar-event.query';
import { RespondToInviteCommand } from './respond-to-invite.command';
import { META } from './respond-to-invite-tool.meta';
import { oneLine } from './utils/calendar-display';
import { EVENT_RESPONSES } from './utils/calendar-graph-path';
import { confirmWrite } from './utils/confirm-write';
import { EventRefSchema } from './utils/event-ref.schema';

const ConfirmSchema = z.object({
  confirmed: z.boolean().meta({
    title: 'Send this response',
    description: 'Confirm to notify the organizer. Leave unchecked to cancel.',
  }),
});

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
      'True when Graph accepted the response. False when the user cancelled, the event was not found, or consent is missing.',
    ),
  message: z.string().describe('Human-readable summary of the outcome.'),
  response: z
    .enum(EVENT_RESPONSES)
    .optional()
    .describe('The response that was sent, when success is true.'),
  consentRequired: z
    .boolean()
    .optional()
    .describe(
      'True when calendar scopes have not been granted yet. The user must reconnect Outlook before calendar tools will work.',
    ),
});

@Injectable()
export class RespondToInviteTool {
  private readonly logger = new Logger(RespondToInviteTool.name);

  public constructor(
    private readonly getCalendarEventQuery: GetCalendarEventQuery,
    private readonly respondToInviteCommand: RespondToInviteCommand,
  ) {}

  @Tool({
    name: 'respond_to_invite',
    title: 'Respond to Invite',
    description:
      'Accept, tentatively accept, or decline an Outlook meeting invitation. Pass eventRef from search_calendar_events without changing it. The user must confirm before the organizer is notified. Invitations have no draft state — the response is sent immediately. If consentRequired is true, ask the user to reconnect Outlook.',
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
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof RespondToInviteOutputSchema>> {
    const parsed = RespondToInviteInputSchema.parse(input);
    const userProfileId = extractUserProfileId(request);
    const loaded = await this.getCalendarEventQuery.run(userProfileId, {
      eventRef: parsed.eventRef,
    });
    if (loaded.success !== true || loaded.event === undefined) {
      return { success: false, message: loaded.message, consentRequired: loaded.consentRequired };
    }
    const confirmation = await confirmWrite({
      context,
      schema: ConfirmSchema,
      message: elicitMessage(parsed.response, parsed.comment, loaded.event),
      logger: this.logger,
      operation: 'respond_to_invite',
      userProfileId: userProfileId.toString(),
    });
    if (confirmation.status === 'unavailable') {
      return { success: false, message: confirmation.message };
    }
    if (confirmation.status !== 'accepted' || confirmation.content.confirmed !== true) {
      this.logger.debug({
        userProfileId: userProfileId.toString(),
        mailbox: obfuscateEmail(parsed.eventRef.mailbox),
        calendarId: parsed.eventRef.calendarId,
        response: parsed.response,
        msg: 'respond_to_invite elicit cancelled',
      });
      return {
        success: false,
        message: 'Invite response was cancelled. The organizer was not notified.',
      };
    }
    return this.respondToInviteCommand.run(userProfileId, parsed);
  }
}

function elicitMessage(
  response: z.infer<typeof RespondToInviteInputSchema>['response'],
  comment: string | undefined,
  snapshot: CalendarEventSnapshot,
): string {
  const action =
    response === 'accept'
      ? 'accept'
      : response === 'tentativelyAccept'
        ? 'tentatively accept'
        : 'decline';
  const organizer =
    snapshot.organizerName !== null && snapshot.organizerEmail !== null
      ? `${oneLine(snapshot.organizerName)} (${snapshot.organizerEmail})`
      : (snapshot.organizerEmail ?? snapshot.organizerName ?? 'the organizer');
  const note =
    comment !== undefined && comment.trim() !== ''
      ? ` The comment sent with it will be: "${oneLine(comment)}".`
      : '';
  return [
    `Confirm to ${action} this invitation.`,
    `Title: ${oneLine(snapshot.subject ?? '(no title)')}.`,
    snapshot.start !== null ? `When: ${snapshot.start.dateTime}.` : undefined,
    `Organizer: ${organizer}.`,
    `The organizer will be notified immediately.${note}`,
  ]
    .filter((line) => line !== undefined)
    .join('\n');
}
