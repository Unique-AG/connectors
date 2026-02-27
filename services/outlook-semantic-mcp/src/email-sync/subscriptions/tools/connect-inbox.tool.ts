import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { SyncDirectoriesCommand } from '~/email-sync/directories-sync/sync-directories.command';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { SubscriptionCreateService } from '../subscription-create.service';

const oneYearAgo = () => {
  const date = new Date();
  date.setFullYear(date.getFullYear() - 1);
  return date;
};

const ConnectInboxInputSchema = z.object({
  dateFrom: z.iso
    .date()
    .transform((value) => new Date(value))
    .refine((date) => date >= oneYearAgo(), { message: 'Minimum date can be one year ago' })
    .describe('Start date for date range filter (ISO format: YYYY-MM-DD)'),
});

const ConnectInboxOutputSchema = z.object({
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
export class ConnectInboxTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly subscriptionCreate: SubscriptionCreateService,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
  ) {}

  @Tool({
    name: 'connect_inbox',
    title: 'Connect Inbox',
    description:
      'Start the knowledge base integration to begin ingesting Microsoft Outlook emails. This creates a subscription with Microsoft Graph to receive notifications when new emails are available.',
    parameters: ConnectInboxInputSchema,
    outputSchema: ConnectInboxOutputSchema,
    annotations: {
      title: 'Connect Inbox',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'play',
      'unique.app/system-prompt':
        'Connects the inbox for outlook email ingestion. Use verify_inbox_connection first to check if it is already running. If already active, inform the user that ingestion is already running.',
    },
  })
  @Span()
  public async connectInbox(
    input: z.infer<typeof ConnectInboxInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeid = extractUserProfileId(request);
    const userProfileId = userProfileTypeid.toString();

    this.logger.log({ userProfileId }, 'Starting knowledge base integration for user');

    // We first sync all directories because if the webhook receives notifications we should be able to process them.
    await this.syncDirectoriesCommand.run(userProfileTypeid);
    const result = await this.subscriptionCreate.subscribe(userProfileTypeid, input);
    const { status, subscription } = result;

    const expiresAt = new Date(subscription.expiresAt);
    const minutesUntilExpiration = Math.floor((expiresAt.getTime() - Date.now()) / (1000 * 60));

    const messages: Record<typeof status, string> = {
      created:
        'Knowledge base integration started successfully. Outlook emails will now be ingested automatically.',
      already_active: 'Knowledge base integration is already active.',
      expiring_soon: `Knowledge base integration is active but expiring in ${minutesUntilExpiration} minutes. It will be automatically renewed.`,
    };

    this.logger.log(
      { userProfileId, subscriptionId: subscription.id, status },
      'Knowledge base integration operation completed',
    );

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
