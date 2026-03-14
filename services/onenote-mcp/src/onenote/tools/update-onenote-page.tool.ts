import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GlobalThrottleMiddleware } from '~/msgraph/global-throttle.middleware';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { extractSafeGraphError } from '~/utils/graph-error.filter';
import { OneNoteGraphService } from '../onenote-graph.service';
import { OneNoteSyncService } from '../onenote-sync.service';

const UpdatePageInputSchema = z.object({
  pageId: z.string().describe('The ID of the page to update'),
  action: z.enum(['append', 'prepend', 'replace']).describe('How to apply the content change'),
  targetId: z
    .string()
    .optional()
    .describe('The data-id of the target element. Defaults to "body" if omitted.'),
  contentHtml: z.string().describe('HTML content to apply'),
});

const UpdatePageOutputSchema = z.object({
  success: z.boolean(),
  pageId: z.string(),
  message: z.string(),
  statusNote: z
    .string()
    .optional()
    .describe(
      'Human-readable status information. Always relay this to the user when present — it explains delays, throttling, or background operations.',
    ),
});

@Injectable()
export class UpdateOneNotePageTool {
  private readonly logger = new Logger(UpdateOneNotePageTool.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly graphService: OneNoteGraphService,
    private readonly syncService: OneNoteSyncService,
  ) {}

  @Tool({
    name: 'update_onenote_page',
    title: 'Update OneNote Page',
    description: 'Append, prepend, or replace content on an existing OneNote page.',
    parameters: UpdatePageInputSchema,
    outputSchema: UpdatePageOutputSchema,
    annotations: {
      title: 'Update OneNote Page',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'edit',
      'unique.app/system-prompt':
        'Use this tool when the user wants to edit, add to, or modify an existing OneNote page. ' +
        'Requires a pageId from a previous search or create result. ' +
        'Use append to add content at the end, prepend to add at the beginning, or replace to overwrite a specific section.',
      'unique.app/tool-format-information':
        'After updating a page, always include a clickable markdown link [open document](oneNoteWebUrl) using the oneNoteWebUrl from the prior search or create result that provided the pageId. ' +
        'Always relay the statusNote to the user when present — it contains important information about delays or background operations.',
    },
  })
  @Span()
  public async updatePage(
    input: z.infer<typeof UpdatePageInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof UpdatePageOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    this.logger.log(
      {
        userProfileId,
        pageId: input.pageId,
        action: input.action,
        targetId: input.targetId,
        contentHtmlLength: input.contentHtml.length,
      },
      'Tool update_onenote_page called',
    );

    const throttleBefore = GlobalThrottleMiddleware.snapshotWaitMs();

    try {
      const client = this.graphClientFactory.createClientForUser(userProfileId);

      const target = input.targetId ? `#${input.targetId}` : 'body';

      const changes = [
        {
          target,
          action: input.action,
          content: input.contentHtml,
        },
      ];

      await this.graphService.updatePage(client, input.pageId, changes);

      this.logger.log({ pageId: input.pageId, action: input.action }, 'Updated OneNote page');

      this.syncService.debouncedSync(userProfileId);

      const throttleWaitMs = GlobalThrottleMiddleware.snapshotWaitMs() - throttleBefore;
      const statusNote = GlobalThrottleMiddleware.buildStatusNote(throttleWaitMs, [
        'The page was updated successfully. A background sync is running so the changes will appear in search results within the next couple of minutes.',
      ]);

      return {
        success: true,
        pageId: input.pageId,
        message: `Page updated successfully (${input.action})`,
        statusNote,
      };
    } catch (error) {
      const safeError = extractSafeGraphError(error);
      this.logger.error({ userProfileId, pageId: input.pageId, ...safeError }, 'Failed to update OneNote page');
      const throttleWaitMs = GlobalThrottleMiddleware.snapshotWaitMs() - throttleBefore;
      const statusNote = GlobalThrottleMiddleware.buildStatusNote(throttleWaitMs, [
        `The page could not be updated: ${safeError.message}`,
      ]);
      return {
        success: false,
        pageId: input.pageId,
        message: `Failed to update page: ${safeError.message}`,
        statusNote,
      };
    }
  }
}
