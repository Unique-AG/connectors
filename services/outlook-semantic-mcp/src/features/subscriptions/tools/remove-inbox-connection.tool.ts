import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { RemoveRootScopeAndDirectoriesCommand } from '~/features/directories-sync/remove-root-scope-and-directories.command';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { SubscriptionRemoveService } from '../subscription-remove.service';
import { META } from './remove-inbox-connection-tool.meta';

const RemoveInboxConnectionInputSchema = z.object({});

const RemoveInboxConnectionOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  subscription: z
    .object({
      id: z.string(),
      status: z.enum(['removed', 'not_found']),
    })
    .nullable(),
});

@Injectable()
export class RemoveInboxConnectionTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly removeRootScopeAndDirectoriesCommand: RemoveRootScopeAndDirectoriesCommand,
    private readonly subscriptionRemove: SubscriptionRemoveService,
  ) {}

  @Tool({
    name: 'remove_inbox_connection',
    title: 'Remove Inbox Connection',
    description:
      'Remove the inbox connection to cease ingesting Microsoft Outlook emails. This removes the subscription with Microsoft Graph.',
    parameters: RemoveInboxConnectionInputSchema,
    outputSchema: RemoveInboxConnectionOutputSchema,
    annotations: {
      title: 'Remove Inbox Connection',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async removeInboxConnection(
    _input: z.infer<typeof RemoveInboxConnectionInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeid = extractUserProfileId(request);
    const userProfileId = userProfileTypeid.toString();

    this.logger.log({ userProfileId, msg: 'Removing inbox connection for user' });

    await this.removeRootScopeAndDirectoriesCommand.run(userProfileTypeid);
    const result = await this.subscriptionRemove.removeByUserProfileId(userProfileTypeid);
    const { status, subscription } = result;

    const messages: Record<typeof status, string> = {
      removed: 'Inbox connection removed successfully. New emails will no longer be ingested.',
      not_found: 'No active inbox connection found. Nothing to remove.',
    };

    this.logger.log({
      msg: 'Inbox connection removal operation completed',
      userProfileId,
      subscriptionId: subscription?.id,
      status,
    });

    return {
      success: true,
      message: messages[status],
      subscription: subscription ? { id: subscription.id, status } : null,
    };
  }
}
