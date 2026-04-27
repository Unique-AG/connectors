import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { isGraphBackend } from '~/utils/backend-config.utils';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { SearchBackend } from '../search/semantic-search-emails.query';
import { OpenEmailQuery } from './open-email.query';
import { META } from './open-email-tool.meta';

const IS_GRAPH_BACKEND = isGraphBackend();

const OpenEmailByIdInputSchema = z.object({
  id: z.string().describe('The id field from a search_emails result.'),
  backend: z
    .nativeEnum(SearchBackend)
    .describe('The backend field from the search_emails result.'),
});

export const EmailDataChunkSchema = z.object({
  id: z.string(),
  startPage: z.number().nullable(),
  endPage: z.number().nullable(),
  order: z.number().nullable(),
  text: z.string(),
});

export const EmailDataSchema = z.object({
  id: z.string(),
  title: z.string().nullable(),
  metadata: z.unknown().nullable(),
  chunks: z.array(EmailDataChunkSchema).optional(),
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
    description: 'Retrieve the full content of an email by its ID returned from search_emails.',
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

    if (!IS_GRAPH_BACKEND) {
      const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
      if (!subscriptionStatus.success) {
        return subscriptionStatus;
      }
    }

    const emailData = await this.openEmailQuery.run(
      userProfileTypeId.toString(),
      input.id,
      input.backend,
    );
    return { success: true, emailData };
  }
}
