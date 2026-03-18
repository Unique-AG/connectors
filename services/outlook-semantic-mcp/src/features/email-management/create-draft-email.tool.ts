import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { GetSubscriptionStatusQuery } from '../subscriptions/get-subscription-status.query';
import { CreateDraftEmailCommand } from './create-draft-email.command';
import { META } from './create-draft-email-tool.meta';

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
  attachmentIds: z
    .array(z.string())
    .optional()
    .describe(
      'IDs of files from the Unique knowledge base to attach to this email. ' +
        'These are content IDs, not file paths. ' +
        'Examples: cont_j23i0ifr44sdn7cz97ubleb7, cont_h346inqws1s3686luftk96yt, cont_tl4uzdijj93r98lcxtk8js9k',
    ),
});

const CreateDraftEmailOutputSchema = z.object({
  success: z.boolean(),
  draftId: z.string().optional(),
  webLink: z.string().optional().describe('Outlook Web App URL to open the draft.'),
  message: z.string(),
  attachmentsFailed: z
    .array(
      z.object({
        contentId: z.string(),
        reason: z.string(),
      }),
    )
    .optional(),
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
    const userProfileTypeId = extractUserProfileId(request);
    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
    if (!subscriptionStatus.success) {
      return subscriptionStatus;
    }
    return this.createDraftEmailCommand.run(userProfileTypeId, input);
  }
}
