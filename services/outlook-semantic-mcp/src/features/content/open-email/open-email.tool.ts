import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { SearchBackend } from '../search/semantic-search-emails.query';
import { OpenEmailQuery } from './open-email.query';
import { META } from './open-email-tool.meta';

const OpenEmailByIdInputSchema = z.object({
  id: z
    .string()
    .describe(
      'The email identifier. Use the `id` field from `openEmailParams` in a `search_emails` result.',
    ),
  idType: z
    .nativeEnum(SearchBackend)
    .describe(
      'The backend type. Use the `idType` field from `openEmailParams` in a `search_emails` result.',
    ),
  mailbox: z
    .email()
    .optional()
    .describe(
      'Delegated mailbox address. Use the `mailbox` field from `openEmailParams` in a `search_emails` result.',
    ),
  parentFolderId: z
    .string()
    .regex(/^[A-Za-z0-9_=-]+$/)
    .optional()
    .describe(
      'The folder containing this email. Use the `parentFolderId` field from `openEmailParams` in a `search_emails` result.',
    ),
  idIsImmutable: z
    .boolean()
    .optional()
    .describe(
      'Whether the id is an immutable ID. Use the `idIsImmutable` field from `openEmailParams` in a `search_emails` result.',
    ),
}).refine((val) => !val.mailbox || val.parentFolderId !== undefined, {
  message: 'parentFolderId is required when mailbox is provided',
  path: ['parentFolderId'],
});

export const EmailDataSchema = z.object({
  id: z.string(),
  title: z.string().nullable(),
  metadata: z.unknown().nullable(),
  text: z.string(),
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
  ) {}

  @Tool({
    name: 'open_email_by_id',
    title: 'Open Email by ID',
    description:
      'Retrieve the full body of an email. Pass the `openEmailParams` object from a `search_emails` result directly as the tool input.',
    parameters: OpenEmailByIdInputSchema,
    outputSchema: OpenEmailByIdOutputSchema,
    annotations: {
      title: 'Open Email by ID',
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

    const emailData = await this.openEmailQuery.run(
      userProfileTypeId.toString(),
      input.id,
      input.idType,
      input.mailbox,
      input.parentFolderId,
      input.idIsImmutable,
    );
    return { success: true, emailData };
  }
}
