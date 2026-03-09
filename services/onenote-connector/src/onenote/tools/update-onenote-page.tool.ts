import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { OneNoteGraphService } from '../onenote-graph.service';

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
});

@Injectable()
export class UpdateOneNotePageTool {
  private readonly logger = new Logger(UpdateOneNotePageTool.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly graphService: OneNoteGraphService,
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

    return {
      success: true,
      pageId: input.pageId,
      message: `Page updated successfully (${input.action})`,
    };
  }
}
