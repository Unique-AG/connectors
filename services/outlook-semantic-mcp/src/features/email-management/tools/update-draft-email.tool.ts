import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { DraftRecipientsSchema, ExistingDraftTargetShape } from '../draft-input.schemas';
import { UpdateDraftEmailCommand } from '../update-draft-email.command';
import { META } from './update-draft-email-tool.meta';

const UpdateDraftEmailInputSchema = z
  .object({
    ...ExistingDraftTargetShape,
    subject: z
      .string()
      .optional()
      .describe('Replacement subject line. Omit to keep the current subject.'),
    content: z
      .string()
      .optional()
      .describe(
        'Replacement body of the draft, written in Markdown. It replaces the WHOLE body, including any quoted earlier thread of a reply draft, so start from the body you read with `open_email` and keep what the user did not ask to change. Raw HTML is not rendered (it is escaped). Omit to keep the current body.',
      ),
    toRecipients: DraftRecipientsSchema.min(1)
      .optional()
      .describe(
        'Replacement list of primary recipients. It replaces the whole list. Omit to keep the current recipients.',
      ),
    ccRecipients: DraftRecipientsSchema.optional().describe(
      'Replacement list of CC recipients. It replaces the whole list; an empty array removes every CC recipient. Omit to keep the current CC recipients.',
    ),
  })
  .refine(
    ({ subject, content, toRecipients, ccRecipients }) =>
      [subject, content, toRecipients, ccRecipients].some((value) => value !== undefined),
    { message: 'Provide at least one of subject, content, toRecipients or ccRecipients.' },
  );

const UpdateDraftEmailOutputSchema = z.object({
  success: z.boolean().describe('True when the draft was updated. False when nothing was changed.'),
  draftId: z
    .string()
    .optional()
    .describe(
      'Microsoft Graph message ID of the updated draft. Present only when success is true.',
    ),
  webLink: z
    .string()
    .optional()
    .describe(
      'Outlook Web App URL to open the draft directly. Present only when success is true and a link could be built.',
    ),
  message: z.string().describe('Human-readable summary of the outcome, success or failure.'),
});

@Injectable()
export class UpdateDraftEmailTool {
  public constructor(private readonly updateDraftEmailCommand: UpdateDraftEmailCommand) {}

  @Tool({
    name: 'update_draft_email',
    title: 'Update Draft Email',
    description:
      'Edits an existing unsent draft in Outlook: subject, body, To and CC recipients. Only the fields you pass change; the body and recipient lists you pass replace the existing ones entirely. **Always read the draft with `open_email` first** (find it with `search_emails` restricted to the Drafts folder, or use the `draftId` returned by `draft_email`) so you keep the parts the user did not ask to change. Fails when the message is no longer a draft. To add or remove attachments use `add_attachments_to_draft_email` and `remove_attachments_from_draft_email`.',
    parameters: UpdateDraftEmailInputSchema,
    outputSchema: UpdateDraftEmailOutputSchema,
    annotations: {
      title: 'Update Draft Email',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async updateDraftEmail(
    input: z.infer<typeof UpdateDraftEmailInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    return this.updateDraftEmailCommand.run(extractUserProfileId(request), input);
  }
}
