import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { GetMailboxTimezoneQuery } from '~/features/user-utils/get-mailbox-timezone.query';
import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { OpenEmailQuery } from './open-email.query';
import { META } from './open-email-tool.meta';

const OpenEmailByIdInputSchema = z
  .object({
    id: z
      .string()
      .describe(
        'Microsoft Graph message id. Use `openEmailParams.id` from a `search_emails` result. Pass the whole object.',
      ),
    mailbox: z
      .email()
      .optional()
      .describe(
        'Delegated mailbox address. Use `openEmailParams.mailbox` from a `search_emails` result.',
      ),
    parentFolderId: z
      .string()
      .regex(/^[A-Za-z0-9+/_=-]+$/)
      .optional()
      .describe(
        'The folder containing this email. Use `openEmailParams.parentFolderId` from a `search_emails` result.',
      ),
    idIsImmutable: z
      .boolean()
      .optional()
      .describe(
        'Whether the id is an immutable ID. Use `openEmailParams.idIsImmutable` from a `search_emails` result.',
      ),
    bodyContentType: z
      .enum(['text', 'html'])
      .optional()
      .describe(
        "Body format. `openEmailParams` sets this to `html` when the message is a draft, and omits it otherwise so the body is plain text. Pass the object through. Edit a draft's HTML and send it back as `content` to `update_draft_email`.",
      ),
    uniqueContentId: z
      .string()
      .optional()
      .describe(
        'Ingested content id from `openEmailParams`. When set, the matched chunks are returned in `chunks` alongside the live Graph body. Pass it through.',
      ),
    chunkIds: z
      .array(z.string())
      .optional()
      .describe(
        'Ids of the semantically matched chunks from `openEmailParams`. Pass them through with `uniqueContentId`.',
      ),
  })
  .refine((val) => !val.mailbox || val.parentFolderId !== undefined, {
    message: 'parentFolderId is required when mailbox is provided',
    path: ['parentFolderId'],
  });

export const EmailDataSchema = z.object({
  id: z.string(),
  title: z.string().nullable(),
  metadata: z.unknown().nullable(),
  text: z
    .string()
    .describe(
      'Full body. Plain text when `bodyContentType` is `text`. HTML when it is `html` — that is the body to edit and send back to `update_draft_email`.',
    ),
  bodyContentType: z
    .enum(['text', 'html'])
    .describe('Format of `text`. `html` only when the input set `bodyContentType: "html"`.'),
  chunks: z
    .string()
    .optional()
    .describe(
      'Semantically matched passages from the ingested email, including attachment text. Present when `uniqueContentId` was passed. The live message body is `text`. When editing a draft, change `text`, not `chunks`.',
    ),
});

const OpenEmailByIdOutputSchema = z.object({
  success: z.boolean(),
  status: z.string().optional(),
  message: z.string().optional(),
  emailData: EmailDataSchema.optional(),
});

@Injectable()
export class OpenEmailTool {
  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly openEmailQuery: OpenEmailQuery,
    private readonly getMailboxTimezoneQuery: GetMailboxTimezoneQuery,
  ) {}

  @Tool({
    name: 'open_email',
    title: 'Open Email',
    description:
      "Retrieve the full body of an email from Microsoft Graph. Search results only carry partial content, so call this whenever a result's `text` does not clearly answer the question, or when the user asks to open or read an email. Pass the `openEmailParams` object directly, including `uniqueContentId` and `chunkIds` when set: those add the matched ingested passages in `chunks`. A draft's `openEmailParams` sets `bodyContentType` to `html`; edit that HTML (`text`) and send it back to `update_draft_email`. Every other message is plain text.",
    parameters: OpenEmailByIdInputSchema,
    outputSchema: OpenEmailByIdOutputSchema,
    annotations: {
      title: 'Open Email',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async openEmailById(
    input: z.infer<typeof OpenEmailByIdInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof OpenEmailByIdOutputSchema>> {
    const userProfileTypeId = extractUserProfileId(request);

    if (!isMicrosoftGraphBackend()) {
      const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
      if (!subscriptionStatus.success) {
        return subscriptionStatus;
      }
    }

    const outputTimeZone = await this.getMailboxTimezoneQuery.run(userProfileTypeId);
    const emailData = await this.openEmailQuery.run({
      userProfileId: userProfileTypeId.toString(),
      id: input.id,
      mailbox: input.mailbox,
      folderId: input.parentFolderId,
      idIsImmutable: input.idIsImmutable,
      bodyContentType: input.bodyContentType,
      uniqueContentId: input.uniqueContentId,
      chunkIds: input.chunkIds,
      outputTimeZone: outputTimeZone,
    });
    return { success: true, emailData };
  }
}
