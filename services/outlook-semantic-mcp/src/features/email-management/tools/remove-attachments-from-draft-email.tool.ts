import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { ConfirmSchema, confirmWrite } from '~/utils/confirm-write';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { ExistingDraftTargetShape } from '../draft-input.schemas';
import { DraftAttachment, GetDraftStateQuery } from '../get-draft-state.query';
import { RemoveAttachmentsFromDraftEmailCommand } from '../remove-attachments-from-draft-email.command';
import { META } from './remove-attachments-from-draft-email-tool.meta';

const RemoveAttachmentsInputSchema = z.object({
  ...ExistingDraftTargetShape,
  fileNames: z
    .array(z.string())
    .min(1)
    .describe(
      'File names of the attachments to remove, exactly as listed in `metadata.attachments` from `open_email` (matching ignores case). Every attachment with a given name is removed.',
    ),
});

const RemoveAttachmentsOutputSchema = z.object({
  success: z
    .boolean()
    .describe('True when every requested attachment was removed. False otherwise.'),
  message: z.string().describe('Human-readable summary of the outcome, success or failure.'),
  removed: z.array(z.string()).optional().describe('File names that were removed.'),
  failed: z
    .array(
      z.object({
        fileName: z.string().describe('The file name of the attachment that could not be removed.'),
        reason: z.string().describe('Why the removal failed.'),
      }),
    )
    .optional()
    .describe('Attachments that could not be removed. Absent when none failed.'),
});

@Injectable()
export class RemoveAttachmentsFromDraftEmailTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly getDraftStateQuery: GetDraftStateQuery,
    private readonly removeAttachmentsFromDraftEmailCommand: RemoveAttachmentsFromDraftEmailCommand,
  ) {}

  @Tool({
    name: 'remove_attachments_from_draft_email',
    title: 'Remove Attachments from Draft Email',
    description:
      'Removes attachments from an existing unsent draft, by file name. The user is asked to confirm the removal before anything is deleted, and a removed attachment cannot be restored. **Read the draft with `open_email` first** to get the exact file names in `metadata.attachments`. Fails when the message is no longer a draft.',
    parameters: RemoveAttachmentsInputSchema,
    outputSchema: RemoveAttachmentsOutputSchema,
    annotations: {
      title: 'Remove Attachments from Draft Email',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async removeAttachments(
    input: z.infer<typeof RemoveAttachmentsInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof RemoveAttachmentsOutputSchema>> {
    const userProfileId = extractUserProfileId(request);

    const draftState = await this.getDraftStateQuery.run({
      userProfileId: userProfileId.toString(),
      draftId: input.draftId,
      idIsImmutable: input.idIsImmutable,
      mailbox: input.mailbox,
    });
    if (draftState.status === 'failed') {
      return { success: false, message: draftState.message };
    }

    const wantedNames = new Set(input.fileNames.map((name) => name.toLowerCase()));
    const toRemove = draftState.attachments.filter(({ name }) =>
      wantedNames.has(name.toLowerCase()),
    );
    const missing = input.fileNames.filter(
      (name) =>
        !toRemove.some((attachment) => attachment.name.toLowerCase() === name.toLowerCase()),
    );
    if (missing.length) {
      return {
        success: false,
        message: `The draft has no attachment named ${missing.map((name) => `"${name}"`).join(', ')}. Nothing was removed. The draft's attachments are: ${this.listNames(draftState.attachments)}.`,
      };
    }

    const confirmation = await confirmWrite({
      context,
      schema: ConfirmSchema,
      message: this.elicitMessage(draftState.subject, toRemove),
      logger: this.logger,
      operation: 'remove_attachments_from_draft_email',
      userProfileId: userProfileId.toString(),
    });
    if (confirmation.status === 'unavailable') {
      return { success: false, message: confirmation.message };
    }
    if (confirmation.status !== 'accepted') {
      return { success: false, message: 'Attachment removal was cancelled. Nothing was removed.' };
    }

    const { removed, failed } = await this.removeAttachmentsFromDraftEmailCommand.run(
      userProfileId,
      {
        draftId: input.draftId,
        idIsImmutable: input.idIsImmutable,
        mailbox: input.mailbox,
        attachments: toRemove,
      },
    );
    return {
      success: failed.length === 0,
      message: failed.length
        ? 'Some attachments could not be removed from the draft.'
        : 'Attachments removed from the draft.',
      removed,
      ...(failed.length && { failed }),
    };
  }

  private listNames(attachments: DraftAttachment[]): string {
    return attachments.length ? attachments.map(({ name }) => `"${name}"`).join(', ') : 'none';
  }

  private elicitMessage(subject: string | null, toRemove: DraftAttachment[]): string {
    return [
      `Remove ${toRemove.length === 1 ? 'this attachment' : 'these attachments'} from the draft "${subject ?? '(no subject)'}"?`,
      ...toRemove.map(({ name }) => `- ${name}`),
      'This cannot be undone. The draft is not sent.',
    ].join('\n');
  }
}
