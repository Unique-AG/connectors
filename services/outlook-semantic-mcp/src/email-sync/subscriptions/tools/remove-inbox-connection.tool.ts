import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { RemoveRootScopeAndDirectoriesCommand } from '~/email-sync/directories-sync/remove-root-scope-and-directories.command';
import { traceAttrs } from '~/email-sync/tracing.utils';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SubscriptionRemoveService } from '../subscription-remove.service';

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
    _meta: {
      'unique.app/icon': 'stop',
      'unique.app/system-prompt':
        'Removes the inbox connection for outlook emails. After removing, new emails will no longer be ingested. Use verify_inbox_connection first to check if it is running.',
    },
  })
  @Span()
  public async removeInboxConnection(
    _input: z.infer<typeof RemoveInboxConnectionInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    traceAttrs({ user_profile_id: userProfileId });

    this.logger.log({ userProfileId }, 'Removing inbox connection for user');

    const userProfileTypeid = convertUserProfileIdToTypeId(userProfileId);

    await this.removeRootScopeAndDirectoriesCommand.run(userProfileTypeid);
    const result = await this.subscriptionRemove.removeByUserProfileId(userProfileTypeid);
    const { status, subscription } = result;

    const messages: Record<typeof status, string> = {
      removed: 'Inbox connection removed successfully. New emails will no longer be ingested.',
      not_found: 'No active inbox connection found. Nothing to remove.',
    };

    this.logger.log(
      { userProfileId, subscriptionId: subscription?.id, status },
      'Inbox connection removal operation completed',
    );

    return {
      success: true,
      message: messages[status],
      subscription: subscription ? { id: subscription.id, status } : null,
    };
  }
}
