import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { OneNoteGraphService } from '../onenote-graph.service';

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
  oneNoteWebUrl: z.string().optional(),
  oneNoteClientUrl: z.string().optional(),
  createdDateTime: z.string().optional(),
  message: z.string().optional(),
});

@Injectable()
export class CreateOneNotePageTool {
  private readonly logger = new Logger(CreateOneNotePageTool.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly graphService: OneNoteGraphService,
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

    return {
      success: true,
      pageId: page.id,
      title: page.title ?? input.title,
      oneNoteWebUrl: page.links?.oneNoteWebUrl?.href,
      oneNoteClientUrl: page.links?.oneNoteClientUrl?.href,
      createdDateTime: page.createdDateTime,
    };
  }
}
