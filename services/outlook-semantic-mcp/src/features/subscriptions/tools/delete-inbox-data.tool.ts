import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, createMeta, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { RemoveRootScopeAndDirectoriesCommand } from '~/features/directories-sync/remove-root-scope-and-directories.command';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { SubscriptionRemoveService } from '../subscription-remove.service';

const DeleteInboxDataInputSchema = z.object({});

const DeleteInboxDataOutputSchema = z.object({
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
export class DeleteInboxDataTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly removeRootScopeAndDirectoriesCommand: RemoveRootScopeAndDirectoriesCommand,
    private readonly subscriptionRemove: SubscriptionRemoveService,
  ) {}

  @Tool({
    name: 'delete_inbox_data',
    title: 'Delete Inbox Data',
    description:
      'Permanently delete all synced email data from Unique and cancel the Microsoft Graph subscription. This stops future email ingestion and removes all previously ingested email content for your inbox from the Unique knowledge base.',
    parameters: DeleteInboxDataInputSchema,
    outputSchema: DeleteInboxDataOutputSchema,
    annotations: {
      title: 'Delete Inbox Data',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: createMeta({
      icon: 'stop',
      systemPrompt:
        'Permanently deletes all synced inbox data for the user from the Unique knowledge base and cancels the Microsoft Graph subscription. After deleting, new emails will no longer be ingested and all previously ingested email content will be removed.',
    }),
  })
  @Span()
  public async deleteInboxData(
    _input: z.infer<typeof DeleteInboxDataInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeid = extractUserProfileId(request);
    const userProfileId = userProfileTypeid.toString();

    this.logger.log({ userProfileId, msg: 'Deleting inbox data for user' });

    await this.removeRootScopeAndDirectoriesCommand.run(userProfileTypeid);
    const result = await this.subscriptionRemove.removeByUserProfileId(userProfileTypeid);
    const { status, subscription } = result;

    const messages: Record<typeof status, string> = {
      removed:
        'Inbox data deleted successfully. All previously ingested emails have been removed from Unique and new emails will no longer be ingested.',
      not_found: 'No active inbox connection found. Nothing to delete.',
    };

    this.logger.log({
      msg: 'Inbox data deletion completed',
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
