import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Message } from '@microsoft/microsoft-graph-types';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { MetricService, Span, TraceService } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { BaseMsGraphTool } from '../../msgraph/base-msgraph.tool';
import { GraphClientFactory } from '../../msgraph/graph-client.factory';
import { normalizeError } from '../../utils/normalize-error';
import { OTEL_ATTRIBUTES } from '../../utils/otel-attributes';

const ListMailsInputSchema = z.object({
  folder: z.string().prefault('inbox').describe('Mail folder to read mails from'),
  limit: z.number().min(1).max(50).prefault(10).describe('Number of emails to retrieve'),
});

@Injectable()
export class ListMailsTool extends BaseMsGraphTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    graphClientFactory: GraphClientFactory,
    metricService: MetricService,
    private readonly traceService: TraceService,
  ) {
    super(graphClientFactory, metricService);
  }

  @Tool({
    name: 'list_mails',
    title: 'List Emails',
    description:
      'List recent emails from a specific Outlook folder. Provides a quick overview of messages with subject, sender, and preview.',
    parameters: ListMailsInputSchema,
    annotations: {
      title: 'List Emails',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'inbox',
      'unique.app/system-prompt':
        'Returns the most recent emails from a folder. If the user does not specify a folder, confirm that inbox is intended; otherwise ask which folder to read. Accept well-known names (inbox, sentitems, drafts, deleteditems) or explicit IDs from list_mail_folders.',
    },
  })
  @Span((options, _context, _request) => ({
    attributes: {
      [OTEL_ATTRIBUTES.OUTLOOK_FOLDER]: options.folder,
      [OTEL_ATTRIBUTES.OUTLOOK_LIMIT]: options.limit,
    },
  }))
  public async listMails(
    { folder, limit }: z.infer<typeof ListMailsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const graphClient = this.getGraphClient(request, this.traceService.getSpan());
    this.incrementActionCounter('list_mails');

    try {
      const messages = await graphClient
        .api(`/me/mailFolders/${folder}/messages`)
        .select('subject,from,receivedDateTime,bodyPreview,importance,isRead')
        .top(limit)
        .orderby('receivedDateTime desc')
        .get();

      return {
        emails: messages.value.map((email: Message) => ({
          id: email.id,
          subject: email.subject,
          from: email.from?.emailAddress?.address,
          fromName: email.from?.emailAddress?.name,
          receivedAt: email.receivedDateTime,
          preview: email.bodyPreview,
          importance: email.importance,
          isRead: email.isRead,
        })),
        count: messages.value.length,
        folder,
      };
    } catch (error) {
      this.incrementActionFailureCounter('list_mails', 'graph_api_error');
      this.logger.error({
        msg: 'Failed to read emails from Outlook',
        error: serializeError(normalizeError(error)),
      });
      throw new InternalServerErrorException(error);
    }
  }
}
