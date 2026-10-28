import * as z from 'zod';

export const DraftRecipientsSchema = z.array(
  z.object({
    name: z.string().optional().describe('The display name of the recipient.'),
    email: z.email().describe('The email address of the recipient.'),
  }),
);

export const DraftAttachmentsSchema = z.array(
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
);

export const ExistingDraftTargetShape = {
  draftId: z
    .string()
    .describe(
      'Microsoft Graph message ID of the draft. Use `openEmailParams.id` from a `search_emails` result with `isDraft: true`, or the `draftId` returned by `draft_email`.',
    ),
  idIsImmutable: z
    .boolean()
    .optional()
    .describe(
      'Whether `draftId` is an immutable ID. Use `openEmailParams.idIsImmutable` from the `search_emails` result; omit for a `draftId` returned by `draft_email`.',
    ),
  mailbox: z
    .string()
    .optional()
    .describe(
      'UPN of the shared mailbox that holds the draft (e.g. "support@company.com"). Use `openEmailParams.mailbox` when it is set. Omit for the signed-in user\'s own mailbox.',
    ),
};
