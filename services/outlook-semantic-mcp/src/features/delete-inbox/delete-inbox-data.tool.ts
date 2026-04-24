import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, createMeta, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { DeleteInboxDataCommand, DeleteInboxDataResult } from './delete-inbox-data.command';

const DeleteInboxDataInputSchema = z.object({});

const DeleteInboxDataOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class DeleteInboxDataTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly deleteInboxDataCommand: DeleteInboxDataCommand) {}

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

    const result = await this.deleteInboxDataCommand.run(userProfileId);

    const mapToolResultToMessage: Record<DeleteInboxDataResult, string> = {
      'deletion-started':
        'Inbox deletion started. All previously ingested emails will be removed from Unique. This may take a few minutes for large inboxes.',
      'deletion-already-in-progress': 'Inbox deletion is already in progress.',
      'inbox-already-deleted': 'Inbox has already been deleted.',
    };

    return {
      success: result === 'deletion-started',
      message: mapToolResultToMessage[result],
    };
  }
}
