import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { SubscriptionCreateService } from '../subscription-create.service';

const ReconnectInboxInputSchema = z.object({});

const ReconnectInboxOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  subscription: z
    .object({
      id: z.string(),
      expiresAt: z.string(),
      minutesUntilExpiration: z.number(),
      status: z.enum(['created', 'already_active', 'expiring_soon']),
    })
    .nullable(),
});

@Injectable()
export class ReconnectInboxTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly subscriptionCreate: SubscriptionCreateService) {}

  @Tool({
    name: 'reconnect_inbox',
    title: 'Reconnect Inbox',
    description:
      'Re-establish the Microsoft Outlook inbox subscription when disconnected or expired. Call `verify_inbox_connection` first to confirm the current status before reconnecting.',
    parameters: ReconnectInboxInputSchema,
    outputSchema: ReconnectInboxOutputSchema,
    annotations: {
      title: 'Reconnect Inbox',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'play',
      'unique.app/system-prompt':
        'Re-establishes the inbox subscription for outlook email ingestion. Use verify_inbox_connection first to check if it is already running. If already active, inform the user that ingestion is already running.',
    },
  })
  @Span()
  public async reconnectInbox(
    _input: z.infer<typeof ReconnectInboxInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeid = extractUserProfileId(request);
    const userProfileId = userProfileTypeid.toString();

    this.logger.log({ userProfileId, msg: 'Reconnecting inbox subscription for user' });

    const result = await this.subscriptionCreate.subscribe(userProfileTypeid);
    const { status, subscription } = result;

    const expiresAt = new Date(subscription.expiresAt);
    const minutesUntilExpiration = Math.floor((expiresAt.getTime() - Date.now()) / (1000 * 60));

    const messages: Record<typeof status, string> = {
      created:
        'Inbox subscription re-established successfully. Outlook emails will now be ingested automatically.',
      already_active: 'Inbox subscription is already active.',
      expiring_soon: `Inbox subscription is active but expiring in ${minutesUntilExpiration} minutes. It will be automatically renewed.`,
    };

    this.logger.log({
      msg: 'Inbox subscription reconnect operation completed',
      userProfileId,
      subscriptionId: subscription.id,
      status,
    });

    return {
      success: true,
      message: messages[status],
      subscription: {
        id: subscription.id,
        expiresAt: expiresAt.toISOString(),
        minutesUntilExpiration,
        status,
      },
    };
  }
}
