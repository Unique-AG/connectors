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

const SendMailInput = z.object({
  to: z.union([z.email(), z.array(z.email())]).describe('Recipient email address'),
  subject: z.string().describe('Email subject'),
  body: z.string().describe('Email body content'),
  isHtml: z.boolean().prefault(false).describe('Whether the body is HTML'),
  cc: z.array(z.email()).optional().describe('Carbon copy recipients'),
  bcc: z.array(z.email()).optional().describe('Blind carbon copy recipients'),
});

@Injectable()
export class SendMailTool extends BaseMsGraphTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    graphClientFactory: GraphClientFactory,
    metricService: MetricService,
    private readonly traceService: TraceService,
  ) {
    super(graphClientFactory, metricService);
  }

  @Tool({
    name: 'send_mail',
    title: 'Send Email',
    description:
      'Send an email immediately via Outlook. Use this for direct email sending with recipients, subject, and body content.',
    parameters: SendMailInput,
    annotations: {
      title: 'Send Email',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'send',
      'unique.app/user-prompt':
        'This tool will immediately send the email. Consider using create_draft_email instead if you want to review the email before sending.',
      'unique.app/system-prompt':
        'Before invoking, ensure to, subject, and body are explicitly provided. If any are missing, ask the user to supply them; do not infer recipients or content. Confirm intent to send now versus drafting if the user appears uncertain. Default isHtml to false unless HTML is requested. If multiple recipients are implied but unspecified, ask the user to list exact email addresses.',
    },
  })
  @Span((options, _context, _request) => ({
    attributes: {
      [OTEL_ATTRIBUTES.RECIPIENT_COUNT]: Array.isArray(options.to) ? options.to.length : 1,
      [OTEL_ATTRIBUTES.IS_HTML]: options.isHtml,
    },
  }))
  public async sendMail(
    { to, subject, body, isHtml, cc, bcc }: z.infer<typeof SendMailInput>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const graphClient = this.getGraphClient(request, this.traceService.getSpan());
    this.incrementActionCounter('send_mail');

    const toRecipients = Array.isArray(to) ? to : [to];

    try {
      const message: Message = {
        subject: subject,
        body: {
          contentType: isHtml ? 'html' : 'text',
          content: body,
        },
        toRecipients: toRecipients.map((email) => ({
          emailAddress: {
            address: email,
          },
        })),
        ccRecipients: cc?.map((email) => ({
          emailAddress: {
            address: email,
          },
        })),
        bccRecipients: bcc?.map((email) => ({
          emailAddress: {
            address: email,
          },
        })),
      };

      await graphClient.api('/me/sendMail').post({ message });

      return {
        success: true,
        message: `Email sent successfully to ${to}`,
      };
    } catch (error) {
      this.incrementActionFailureCounter('send_mail', 'graph_api_error');
      this.logger.error({
        msg: 'Failed to send email via Outlook',
        error: serializeError(normalizeError(error)),
      });
      throw new InternalServerErrorException(error);
    }
  }
}
