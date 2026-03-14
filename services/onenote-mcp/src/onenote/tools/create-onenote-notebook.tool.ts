import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GlobalThrottleMiddleware } from '~/msgraph/global-throttle.middleware';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { extractSafeGraphError } from '~/utils/graph-error.filter';
import { OneNoteGraphService } from '../onenote-graph.service';

const CreateNotebookInputSchema = z.object({
  displayName: z.string().describe('Display name of the new notebook'),
});

const CreateNotebookOutputSchema = z.object({
  success: z.boolean(),
  notebookId: z.string().optional(),
  displayName: z.string().optional(),
  oneNoteWebUrl: z
    .string()
    .optional()
    .describe('Direct link to open this notebook in OneNote. Use this for markdown links.'),
  createdDateTime: z.string().optional(),
  message: z.string().optional(),
  statusNote: z
    .string()
    .optional()
    .describe(
      'Human-readable status information. Always relay this to the user when present — it explains delays, throttling, or background operations.',
    ),
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
      'unique.app/system-prompt':
        'Use this tool only when the user explicitly asks to create a new OneNote notebook. ' +
        'Do not create notebooks unprompted — for writing new content, prefer create_onenote_page which auto-creates sections as needed.',
      'unique.app/tool-format-information':
        'After creating a notebook, always include a clickable markdown link [open document](oneNoteWebUrl) using the oneNoteWebUrl field so the user can open the notebook directly. ' +
        'Always relay the statusNote to the user when present — it contains important information about delays or background operations.',
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

    this.logger.log(
      { userProfileId, displayName: input.displayName },
      'Tool create_onenote_notebook called',
    );

    const throttleBefore = GlobalThrottleMiddleware.snapshotWaitMs();

    try {
      const client = this.graphClientFactory.createClientForUser(userProfileId);
      const notebook = await this.graphService.createNotebook(client, input.displayName);

      this.logger.log(
        { notebookId: notebook.id, displayName: input.displayName },
        'Created OneNote notebook',
      );

      const throttleWaitMs = GlobalThrottleMiddleware.snapshotWaitMs() - throttleBefore;
      const statusNote = GlobalThrottleMiddleware.buildStatusNote(throttleWaitMs, [
        'The notebook was created successfully.',
      ]);

      return {
        success: true,
        notebookId: notebook.id,
        displayName: notebook.displayName,
        oneNoteWebUrl: notebook.links?.oneNoteWebUrl?.href,
        createdDateTime: notebook.createdDateTime,
        statusNote,
      };
    } catch (error) {
      const safeError = extractSafeGraphError(error);
      this.logger.error({ userProfileId, ...safeError }, 'Failed to create OneNote notebook');
      const throttleWaitMs = GlobalThrottleMiddleware.snapshotWaitMs() - throttleBefore;
      const statusNote = GlobalThrottleMiddleware.buildStatusNote(throttleWaitMs, [
        `The notebook could not be created: ${safeError.message}`,
      ]);
      return {
        success: false,
        message: `Failed to create notebook: ${safeError.message}`,
        statusNote,
      };
    }
  }
}
