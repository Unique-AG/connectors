import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { CreateDraftEmailCommand } from './create-draft-email.command';

const CreateDraftEmailInputSchema = z.object({
  subject: z.string().describe('The subject line of the draft email.'),
  content: z
    .string()
    .describe(
      'The body content of the draft email. It can be html / text but contentType has to be specied correctly',
    ),
  contentType: z
    .enum(['html', 'text'])
    .describe(
      'The format of the email body content. Use "html" for rich HTML content or "text" for plain text.',
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
        filename: z.string().describe('The name of the file to attach, including its extension.'),
        contentBytes: z.string().describe('The base64-encoded content of the attachment.'),
        contentType: z
          .string()
          .describe('The MIME type of the attachment (e.g. "application/pdf", "image/png").'),
      }),
    )
    .optional()
    .describe('Optional list of file attachments to include in the draft email.'),
});

const CreateDraftEmailOutputSchema = z.object({
  success: z.boolean(),
  draftId: z.string().optional(),
  message: z.string(),
});

@Injectable()
export class CreateDraftEmailTool {
  public constructor(private readonly createDraftEmailCommand: CreateDraftEmailCommand) {}

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
    _meta: {
      'unique.app/icon': 'mail',
      'unique.app/system-prompt':
        "Creates a draft email in the user's Outlook mailbox. Provide subject, body content and type (html or text), and at least one recipient. Optionally include CC recipients and base64-encoded file attachments. The draft is saved and can be reviewed or sent later.",
    },
  })
  @Span()
  public async createDraftEmail(
    input: z.infer<typeof CreateDraftEmailInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeId = extractUserProfileId(request);
    return this.createDraftEmailCommand.run(userProfileTypeId, input);
  }
}
