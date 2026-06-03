import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { isString } from 'remeda';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { CreateDraftEmailCommand } from '../create-draft-email.command';
import { META } from './create-draft-email-tool.meta';

const SharedEmailFields = z.object({
  subject: z.string().describe('The subject line of the draft email.'),
  content: z
    .string()
    .describe(
      'The body content of the draft email, written in Markdown. Supports paragraphs, line breaks, **bold**, *italic*, bullet and numbered lists, [links](https://example.com), blockquotes, and inline `code`. Raw HTML is not rendered (it is escaped) — use Markdown syntax instead.',
    ),
  ccRecipients: z
    .array(
      z.object({
        name: z.string().optional().describe('The display name of the CC recipient.'),
        email: z.email().describe('The email address of the CC recipient.'),
      }),
    )
    .optional()
    .describe(
      'The list of CC (carbon copy) recipients for the email. For reply drafts, Graph fills CC recipients from the original thread — omit this field when using type: "reply".',
    ),
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
  mailbox: z
    .string()
    .optional()
    .describe(
      'UPN of the shared mailbox to create the draft in (e.g. "support@company.com"). Omit to create the draft in the signed-in user\'s own mailbox.',
    ),
});

const FreshDraftInputSchema = SharedEmailFields.extend({
  type: z.literal('draft').describe('Create a fresh draft email.'),
  toRecipients: z
    .array(
      z.object({
        name: z.string().optional().describe('The display name of the recipient.'),
        email: z.email().describe('The email address of the recipient.'),
      }),
    )
    .describe('The list of primary recipients for the email.'),
});

const ReplyDraftInputSchema = SharedEmailFields.extend({
  type: z.literal('reply').describe('Create a reply-all draft for an existing email.'),
  inReplyToMessageId: z
    .string()
    .describe(
      'The msGraphMessageId field from search_emails or outlook_email_search results for the email being replied to. Graph pre-fills all original recipients — do not pass toRecipients or ccRecipients.',
    ),
});

const CreateDraftEmailInputSchema = z.discriminatedUnion('type', [
  FreshDraftInputSchema,
  ReplyDraftInputSchema,
]);

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
  public constructor(private readonly createDraftEmailCommand: CreateDraftEmailCommand) {}

  @Tool({
    name: 'draft_email',
    title: 'Draft Email',
    description:
      'Creates a draft email in Outlook. Pass type: "draft" for a fresh draft (toRecipients required; optionally pass mailbox for a shared mailbox). Pass type: "reply" with inReplyToMessageId for a reply-all draft (Graph pre-fills recipients from the original thread; optionally pass mailbox for a shared mailbox). The draft is saved but not sent.',
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
    const chatId = _context.mcpRequest.params._meta?.chatId;
    const result = await this.createDraftEmailCommand.run(userProfileId, {
      ...input,
      chatId: isString(chatId) ? chatId : null,
    });
    if (input.type === 'reply' && result.success) {
      return {
        ...result,
        message: `${result.message} All original recipients are pre-filled — review before sending.`,
      };
    }
    return result;
  }
}
