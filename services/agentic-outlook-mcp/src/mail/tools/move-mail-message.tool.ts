import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { MetricService, Span, TraceService } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { BaseMsGraphTool } from '../../msgraph/base-msgraph.tool';
import { GraphClientFactory } from '../../msgraph/graph-client.factory';
import { normalizeError } from '../../utils/normalize-error';
import { OTEL_ATTRIBUTES } from '../../utils/otel-attributes';

const MoveMailMessageInputSchema = z.object({
  messageId: z.string().describe('The ID of the message to move'),
  destinationFolderId: z
    .string()
    .describe(
      'The ID or well-known name of the destination folder (e.g., "inbox", "deleteditems", "drafts", "sentitems", or a specific folder ID)',
    ),
});

@Injectable()
export class MoveMailMessageTool extends BaseMsGraphTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    graphClientFactory: GraphClientFactory,
    metricService: MetricService,
    private readonly traceService: TraceService,
  ) {
    super(graphClientFactory, metricService);
  }

  @Tool({
    name: 'move_mail_message',
    title: 'Move Email to Folder',
    description:
      'Move an email message to a different folder in Outlook. Supports both well-known folder names and specific folder IDs for organization.',
    parameters: MoveMailMessageInputSchema,
    annotations: {
      title: 'Move Email to Folder',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'folder-input',
      'unique.app/system-prompt':
        'Before invoking, ensure both messageId and destinationFolderId are provided. If destinationFolderId is unknown, ask the user or first list folders with list_mail_folders and then proceed. Accept well-known names (inbox, deleteditems, drafts, sentitems) or explicit IDs. If messageId is unknown, request it or suggest finding it via search_email or list_mails.',
    },
  })
  @Span((options, _context, _request) => ({
    attributes: {
      [OTEL_ATTRIBUTES.MESSAGE_ID]: options.messageId,
      [OTEL_ATTRIBUTES.DESTINATION_FOLDER]: options.destinationFolderId,
    },
  }))
  public async moveMailMessage(
    { messageId, destinationFolderId }: z.infer<typeof MoveMailMessageInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const graphClient = this.getGraphClient(request, this.traceService.getSpan());
    this.incrementActionCounter('move_mail_message');

    try {
      const originalMessage = await graphClient
        .api(`/me/messages/${messageId}`)
        .select('id,subject,parentFolderId')
        .get();

      const movedMessage = await graphClient.api(`/me/messages/${messageId}/move`).post({
        destinationId: destinationFolderId,
      });

      let destinationFolderName = destinationFolderId;
      try {
        const destinationFolder = await graphClient
          .api(`/me/mailFolders/${destinationFolderId}`)
          .select('displayName')
          .get();

        destinationFolderName = destinationFolder.displayName || destinationFolderId;
      } catch (folderError) {
        this.logger.debug({
          msg: 'Could not retrieve destination folder name',
          destinationFolderId,
          error: serializeError(normalizeError(folderError)),
        });
      }

      this.logger.debug({
        msg: 'Message moved to new folder',
        messageId,
        originalFolderId: originalMessage.parentFolderId,
        destinationFolderId,
        destinationFolderName,
        subject: originalMessage.subject,
      });

      return {
        success: true,
        messageId: movedMessage.id,
        originalFolderId: originalMessage.parentFolderId,
        destinationFolderId: movedMessage.parentFolderId,
        destinationFolderName,
        subject: originalMessage.subject,
        message: `Message moved to "${destinationFolderName}" folder successfully`,
      };
    } catch (error) {
      this.incrementActionFailureCounter('move_mail_message', 'graph_api_error');
      this.logger.error({
        msg: 'Failed to move mail message in Outlook',
        messageId,
        destinationFolderId,
        error: serializeError(normalizeError(error)),
      });
      throw new InternalServerErrorException(error);
    }
  }
}
