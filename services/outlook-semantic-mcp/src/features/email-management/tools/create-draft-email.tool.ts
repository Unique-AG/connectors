import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { isString } from 'remeda';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { GetSubscriptionStatusQuery } from '../../subscriptions/get-subscription-status.query';
import { CreateDraftEmailCommand } from '../create-draft-email.command';
import { META } from './create-draft-email-tool.meta';

const CreateDraftEmailInputSchema = z.object({
  subject: z.string().describe('The subject line of the draft email.'),
  content: z
    .string()
    .describe(
      'The body content of the draft email. Must match the format declared in contentType: raw HTML markup when "html", plain text when "text".',
    ),
  toRecipients: z
    .array(
      z.object({
        name: z.string().optional().describe('The display name of the recipient.'),
        email: z.email().describe('The email address of the recipient.'),
      }),
    )
    .describe('The list of primary recipients for the email.'),
  ccRecipients: z
    .array(
      z.object({
        name: z.string().optional().describe('The display name of the CC recipient.'),
        email: z.email().describe('The email address of the CC recipient.'),
      }),
    )
    .optional()
    .describe('The list of CC (carbon copy) recipients for the email.'),
  attachments: z
    .array(
      z.object({
        fileName: z
          .string()
          .describe(
            'The file name that will appear on the attachment in the email, including extension (e.g. "report.pdf").',
          ),
        data: z
          .string()
          .describe(
            'URI identifying the file content. Two schemes are supported:\n' +
              '- unique://content/{contentId} — file from the Unique knowledge base; use the content ID (e.g. unique://content/cont_a2vgv63szfwudzstjx7ihf3n).\n' +
              '- data:[mediatype];base64,<base64data> — inline base64-encoded content with an explicit MIME type.\n' +
              'External URLs (https://) are not supported.',
          ),
      }),
    )
    .optional()
    .describe(
      'Files to attach to the draft. Each entry pairs a display file name with a URI pointing to the file content. Omit entirely when no attachments are needed.',
    ),
});

const CreateDraftEmailOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when the draft was created in Outlook, even if some attachments failed. False only when the draft itself could not be created.',
    ),
  draftId: z
    .string()
    .optional()
    .describe(
      'Microsoft Graph message ID of the created draft. Present only when success is true.',
    ),
  webLink: z
    .string()
    .optional()
    .describe(
      'Outlook Web App URL to open the draft directly. Present only when success is true and Graph returned a webLink.',
    ),
  message: z.string().describe('Human-readable summary of the outcome, success or failure.'),
  attachmentsFailed: z
    .array(
      z.object({
        fileName: z.string().describe('The file name of the attachment that could not be added.'),
        reason: z.string().describe('Why the attachment failed.'),
      }),
    )
    .optional()
    .describe(
      'Attachments that could not be added to the draft. Present only when success is true and at least one attachment failed; absent otherwise.',
    ),
});

@Injectable()
export class CreateDraftEmailTool {
  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly createDraftEmailCommand: CreateDraftEmailCommand,
  ) {}

  @Tool({
    name: 'create_draft_email',
    title: 'Create Draft Email',
    description:
      'Creates a draft email in the connected Outlook mailbox with the given subject, body, recipients, and optional attachments. The draft is saved but not sent.',
    parameters: CreateDraftEmailInputSchema,
    outputSchema: CreateDraftEmailOutputSchema,
    annotations: {
      title: 'Create Draft Email',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async createDraftEmail(
    input: z.infer<typeof CreateDraftEmailInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = extractUserProfileId(request);
    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileId);
    if (!subscriptionStatus.success) {
      return subscriptionStatus;
    }
    const chatId = _context.mcpRequest.params._meta?.chatId;
    return this.createDraftEmailCommand.run(userProfileId, {
      ...input,
      chatId: isString(chatId) ? chatId : null,
    });
  }
}
