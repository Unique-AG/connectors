import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { MailFolder } from '@microsoft/microsoft-graph-types';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { MetricService, Span, TraceService } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { BaseMsGraphTool } from '../../msgraph/base-msgraph.tool';
import { GraphClientFactory } from '../../msgraph/graph-client.factory';
import { normalizeError } from '../../utils/normalize-error';
import { OTEL_ATTRIBUTES } from '../../utils/otel-attributes';

const ListMailFoldersInputSchema = z.object({
  includeChildFolders: z.boolean().prefault(false).describe('Whether to include child folders'),
  limit: z.number().min(1).max(100).prefault(20).describe('Number of folders to retrieve'),
});

@Injectable()
export class ListMailFoldersTool extends BaseMsGraphTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    graphClientFactory: GraphClientFactory,
    metricService: MetricService,
    private readonly traceService: TraceService,
  ) {
    super(graphClientFactory, metricService);
  }

  @Tool({
    name: 'list_mail_folders',
    title: 'List Mail Folders',
    description:
      'List all mail folders in Outlook with their IDs, names, and message counts. Essential for discovering folder structure and obtaining folder IDs.',
    parameters: ListMailFoldersInputSchema,
    annotations: {
      title: 'List Mail Folders',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'folder-tree',
      'unique.app/system-prompt':
        'Use this tool to discover available mail folders and their IDs. The folder IDs returned can be used with other tools like move_mail_message, search_email, and list_mail_folder_messages. Set includeChildFolders to true to see the complete folder hierarchy.',
    },
  })
  @Span((options, _context, _request) => ({
    attributes: {
      [OTEL_ATTRIBUTES.OUTLOOK_LIMIT]: options.limit,
      [OTEL_ATTRIBUTES.INCLUDE_ATTACHMENTS]: options.includeChildFolders,
    },
  }))
  public async listMailFolders(
    { includeChildFolders, limit }: z.infer<typeof ListMailFoldersInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const graphClient = this.getGraphClient(request, this.traceService.getSpan());
    this.incrementActionCounter('list_mail_folders');

    try {
      const response = await graphClient
        .api('/me/mailFolders')
        .select('id,displayName,parentFolderId,childFolderCount,unreadItemCount,totalItemCount')
        .top(limit)
        .get();

      let folders = response.value.map((folder: MailFolder) => ({
        id: folder.id,
        displayName: folder.displayName,
        parentFolderId: folder.parentFolderId,
        childFolderCount: folder.childFolderCount,
        unreadItemCount: folder.unreadItemCount,
        totalItemCount: folder.totalItemCount,
      }));

      if (includeChildFolders) {
        const foldersWithChildren = await Promise.all(
          folders.map(async (folder: MailFolder) => {
            if (folder.childFolderCount && folder.childFolderCount > 0) {
              try {
                const childResponse = await graphClient
                  .api(`/me/mailFolders/${folder.id}/childFolders`)
                  .select(
                    'id,displayName,parentFolderId,childFolderCount,unreadItemCount,totalItemCount',
                  )
                  .get();

                return {
                  ...folder,
                  childFolders: childResponse.value.map((childFolder: MailFolder) => ({
                    id: childFolder.id,
                    displayName: childFolder.displayName,
                    parentFolderId: childFolder.parentFolderId,
                    childFolderCount: childFolder.childFolderCount,
                    unreadItemCount: childFolder.unreadItemCount,
                    totalItemCount: childFolder.totalItemCount,
                  })),
                };
              } catch (error) {
                this.logger.warn({
                  msg: 'Failed to fetch child folders',
                  folderId: folder.id,
                  error: serializeError(normalizeError(error)),
                });
                return folder;
              }
            }
            return folder;
          }),
        );
        folders = foldersWithChildren;
      }

      return {
        folders,
        count: folders.length,
        includeChildFolders,
      };
    } catch (error) {
      this.incrementActionFailureCounter('list_mail_folders', 'graph_api_error');
      this.logger.error({
        msg: 'Failed to list mail folders from Outlook',
        error: serializeError(normalizeError(error)),
      });
      throw new InternalServerErrorException(error);
    }
  }
}
