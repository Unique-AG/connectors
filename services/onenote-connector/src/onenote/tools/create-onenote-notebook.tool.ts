import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { OneNoteGraphService } from '../onenote-graph.service';

const CreateNotebookInputSchema = z.object({
  displayName: z.string().describe('Display name of the new notebook'),
});

const CreateNotebookOutputSchema = z.object({
  success: z.boolean(),
  notebookId: z.string().optional(),
  displayName: z.string().optional(),
  oneNoteWebUrl: z.string().optional(),
  createdDateTime: z.string().optional(),
  message: z.string().optional(),
});

@Injectable()
export class CreateOneNoteNotebookTool {
  private readonly logger = new Logger(CreateOneNoteNotebookTool.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly graphService: OneNoteGraphService,
  ) {}

  @Tool({
    name: 'create_onenote_notebook',
    title: 'Create OneNote Notebook',
    description: 'Create a new OneNote notebook for the authenticated user.',
    parameters: CreateNotebookInputSchema,
    outputSchema: CreateNotebookOutputSchema,
    annotations: {
      title: 'Create OneNote Notebook',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'book',
    },
  })
  @Span()
  public async createNotebook(
    input: z.infer<typeof CreateNotebookInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof CreateNotebookOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const notebook = await this.graphService.createNotebook(client, input.displayName);

    this.logger.log(
      { notebookId: notebook.id, displayName: input.displayName },
      'Created OneNote notebook',
    );

    return {
      success: true,
      notebookId: notebook.id,
      displayName: notebook.displayName,
      oneNoteWebUrl: notebook.links?.oneNoteWebUrl?.href,
      createdDateTime: notebook.createdDateTime,
    };
  }
}
