import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { isString } from 'remeda';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { AddAttachmentsToDraftEmailCommand } from '../add-attachments-to-draft-email.command';
import { DraftAttachmentsSchema, ExistingDraftTargetShape } from '../draft-input.schemas';
import { GetDraftStateQuery } from '../get-draft-state.query';
import { META } from './add-attachments-to-draft-email-tool.meta';

const AddAttachmentsInputSchema = z.object({
  ...ExistingDraftTargetShape,
  attachments: DraftAttachmentsSchema.min(1).describe(
    'Files to attach to the draft. Each entry pairs a display file name with a URI pointing to the file content.',
  ),
});

const AddAttachmentsOutputSchema = z.object({
  success: z
    .boolean()
    .describe(
      'True when at least one attachment was added. False when the draft could not be used or every attachment failed.',
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
    .describe('Attachments that could not be added. Absent when all of them were added.'),
});

@Injectable()
export class AddAttachmentsToDraftEmailTool {
  public constructor(
    private readonly getDraftStateQuery: GetDraftStateQuery,
    private readonly addAttachmentsToDraftEmailCommand: AddAttachmentsToDraftEmailCommand,
  ) {}

  @Tool({
    name: 'add_attachments_to_draft_email',
    title: 'Add Attachments to Draft Email',
    description:
      'Adds files to an existing unsent draft. The files already on the draft stay. Find the draft with `search_emails` restricted to the Drafts folder (`isDraft: true`) or use the `draftId` returned by `draft_email`. Fails when the message is no longer a draft.',
    parameters: AddAttachmentsInputSchema,
    outputSchema: AddAttachmentsOutputSchema,
    annotations: {
      title: 'Add Attachments to Draft Email',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async addAttachments(
    input: z.infer<typeof AddAttachmentsInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof AddAttachmentsOutputSchema>> {
    const userProfileId = extractUserProfileId(request);
    const chatId = context.mcpRequest.params._meta?.chatId;

    const draftState = await this.getDraftStateQuery.run({
      userProfileId: userProfileId.toString(),
      draftId: input.draftId,
      idIsImmutable: input.idIsImmutable,
      mailbox: input.mailbox,
    });
    if (draftState.status === 'failed') {
      return { success: false, message: draftState.message };
    }

    const { attachmentsFailed } = await this.addAttachmentsToDraftEmailCommand.run(userProfileId, {
      draftId: input.draftId,
      attachments: input.attachments,
      chatId: isString(chatId) ? chatId : null,
      mailbox: input.mailbox,
      idIsImmutable: input.idIsImmutable,
    });

    if (!attachmentsFailed.length) {
      return { success: true, message: 'Attachments added to the draft.' };
    }
    const addedAny = attachmentsFailed.length < input.attachments.length;
    return {
      success: addedAny,
      message: addedAny
        ? 'Some attachments could not be added to the draft.'
        : 'No attachment could be added to the draft.',
      attachmentsFailed,
    };
  }
}
