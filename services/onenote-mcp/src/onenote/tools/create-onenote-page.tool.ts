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

const CreatePageInputSchema = z.object({
  notebookName: z
    .string()
    .optional()
    .describe('Name of the notebook. If omitted, the first available notebook is used.'),
  sectionName: z
    .string()
    .describe(
      'Name of the section to create the page in. Created automatically if it does not exist.',
    ),
  title: z.string().describe('Title of the new page'),
  contentHtml: z.string().describe('HTML content for the page body'),
});

const CreatePageOutputSchema = z.object({
  success: z.boolean(),
  pageId: z.string().optional(),
  title: z.string().optional(),
  oneNoteWebUrl: z
    .string()
    .optional()
    .describe('Direct link to open this page in OneNote. Use this for markdown links.'),
  oneNoteClientUrl: z.string().optional(),
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
export class CreateOneNotePageTool {
  private readonly logger = new Logger(CreateOneNotePageTool.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly graphService: OneNoteGraphService,
    private readonly syncService: OneNoteSyncService,
  ) {}

  @Tool({
    name: 'create_onenote_page',
    title: 'Create OneNote Page',
    description:
      'Create a new page in a OneNote notebook section. The section is created if it does not exist.',
    parameters: CreatePageInputSchema,
    outputSchema: CreatePageOutputSchema,
    annotations: {
      title: 'Create OneNote Page',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'plus',
      'unique.app/system-prompt':
        'Use this tool when the user wants to save, write, or store new content in OneNote. ' +
        'This includes creating notes, saving summaries, drafting documents, or capturing any information as a new page. ' +
        'If the user does not specify a notebook or section, pick a sensible default.',
      'unique.app/tool-format-information':
        'After creating a page, always include a clickable markdown link [open document](oneNoteWebUrl) using the oneNoteWebUrl field so the user can open the page directly. ' +
        'Always relay the statusNote to the user when present — it contains important information about delays or background operations.',
    },
  })
  @Span()
  public async createPage(
    input: z.infer<typeof CreatePageInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof CreatePageOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    this.logger.log(
      {
        userProfileId,
        notebookName: input.notebookName,
        sectionName: input.sectionName,
        title: input.title,
        contentHtmlLength: input.contentHtml.length,
      },
      'Tool create_onenote_page called',
    );

    const throttleBefore = GlobalThrottleMiddleware.snapshotWaitMs();

    try {
      const client = this.graphClientFactory.createClientForUser(userProfileId);

      const notebooks = await this.graphService.listNotebooks(client);
      const notebook = input.notebookName
        ? notebooks.find((nb) => nb.displayName === input.notebookName)
        : notebooks[0];

      if (!notebook) {
        return { success: false, message: `Notebook "${input.notebookName}" not found` };
      }

      const sections = await this.graphService.listSections(client, notebook.id);
      let section = sections.find((s) => s.displayName === input.sectionName);

      if (!section) {
        section = await this.graphService.createSection(client, notebook.id, input.sectionName);
      }

      const page = await this.graphService.createPage(
        client,
        section.id,
        input.title,
        input.contentHtml,
      );

      this.logger.log({ pageId: page.id, title: input.title }, 'Created OneNote page');

      this.syncService.debouncedSync(userProfileId);

      const throttleWaitMs = GlobalThrottleMiddleware.snapshotWaitMs() - throttleBefore;
      const statusNote = GlobalThrottleMiddleware.buildStatusNote(throttleWaitMs, [
        'The page was created successfully. A background sync is running so it will appear in search results within the next couple of minutes.',
      ]);

      return {
        success: true,
        pageId: page.id,
        title: page.title ?? input.title,
        oneNoteWebUrl: page.links?.oneNoteWebUrl?.href,
        oneNoteClientUrl: page.links?.oneNoteClientUrl?.href,
        createdDateTime: page.createdDateTime,
        statusNote,
      };
    } catch (error) {
      const safeError = extractSafeGraphError(error);
      this.logger.error({ userProfileId, ...safeError }, 'Failed to create OneNote page');
      const throttleWaitMs = GlobalThrottleMiddleware.snapshotWaitMs() - throttleBefore;
      const statusNote = GlobalThrottleMiddleware.buildStatusNote(throttleWaitMs, [
        `The page could not be created: ${safeError.message}`,
      ]);
      return {
        success: false,
        message: `Failed to create page: ${safeError.message}`,
        statusNote,
      };
    }
  }
}
