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
      'File names of the attachments to remove, exactly as listed in `metadata.attachments` from `open_email` (matching ignores case). Every non-inline attachment with a given name is removed. Inline images (`isInline: true`) are left in place unless `includeInline` is true.',
    ),
  includeInline: z
    .boolean()
    .optional()
    .describe(
      'Set true only when the user explicitly asked to remove an inline image (a signature image or a picture embedded in the body). Otherwise inline attachments are skipped, because the body still references them and removing them leaves a broken image.',
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
      'Removes attachments from an existing unsent draft, by file name. The user is asked to confirm the removal before anything is deleted, and a removed attachment cannot be restored. Inline images are skipped unless `includeInline` is true and the user explicitly asked for them. **Read the draft with `open_email` first** (pass `openEmailParams`) to get the exact file names in `metadata.attachments`. Fails when the message is no longer a draft.',
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

    const { toRemove, missing, skippedInline } = this.selectAttachments(
      draftState.attachments,
      input.fileNames,
      input.includeInline === true,
    );
    if (missing.length) {
      return {
        success: false,
        message: `The draft has no attachment named ${missing.map((name) => `"${name}"`).join(', ')}. Nothing was removed. The draft's attachments are: ${this.listNames(draftState.attachments)}.`,
      };
    }
    if (!toRemove.length) {
      return {
        success: false,
        message: `${this.inlineSkippedMessage(skippedInline)} Nothing was removed.`,
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
    const skippedNote = skippedInline.length ? ` ${this.inlineSkippedMessage(skippedInline)}` : '';
    return {
      success: failed.length === 0 && skippedInline.length === 0,
      message: failed.length
        ? `Some attachments could not be removed from the draft.${skippedNote}`
        : `Attachments removed from the draft.${skippedNote}`,
      removed,
      ...(failed.length && { failed }),
    };
  }

  private selectAttachments(
    attachments: DraftAttachment[],
    fileNames: string[],
    includeInline: boolean,
  ): { toRemove: DraftAttachment[]; missing: string[]; skippedInline: DraftAttachment[] } {
    const wantedNames = new Set(fileNames.map((name) => name.toLowerCase()));
    const named = attachments.filter(({ name }) => wantedNames.has(name.toLowerCase()));
    const missing = fileNames.filter(
      (name) => !named.some((attachment) => attachment.name.toLowerCase() === name.toLowerCase()),
    );
    const skippedInline = includeInline ? [] : named.filter((attachment) => attachment.isInline);
    const toRemove = includeInline ? named : named.filter((attachment) => !attachment.isInline);
    return { toRemove, missing, skippedInline };
  }

  private listNames(attachments: DraftAttachment[]): string {
    return attachments.length
      ? attachments.map((attachment) => this.formatName(attachment)).join(', ')
      : 'none';
  }

  private formatName(attachment: DraftAttachment): string {
    return `"${attachment.name}"${attachment.isInline ? ' (inline image)' : ''}`;
  }

  private inlineSkippedMessage(skippedInline: DraftAttachment[]): string {
    const names = skippedInline.map((attachment) => this.formatName(attachment)).join(', ');
    return `Left inline images in place: ${names}. They are referenced from the body, so removing them leaves a broken image. Pass includeInline: true only when the user explicitly asked to remove them.`;
  }

  private elicitMessage(subject: string | null, toRemove: DraftAttachment[]): string {
    return [
      `Remove ${toRemove.length === 1 ? 'this attachment' : 'these attachments'} from the draft "${subject ?? '(no subject)'}"?`,
      ...toRemove.map(
        (attachment) => `- ${attachment.name}${attachment.isInline ? ' (inline image)' : ''}`,
      ),
      'This cannot be undone. The draft is not sent.',
    ].join('\n');
  }
}
