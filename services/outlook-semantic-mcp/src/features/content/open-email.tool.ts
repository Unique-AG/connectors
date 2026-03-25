import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { META } from './open-email-tool.meta';

const OpenEmailByIdInputSchema = z.object({
  id: z.string().describe('The content ID returned by the search_emails tool, e.g. "cont_zwgng9aoz0gbo6qxgnwese7g".'),
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
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
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
  ) {
    const userProfileTypeId = extractUserProfileId(request);

    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
    if (!subscriptionStatus.success) {
      return subscriptionStatus;
    }

    const emailData = await this.uniqueApi.content.getContentById({ contentId: input.id });
    return OpenEmailByIdOutputSchema.encode({
      success: true,
      emailData,
    });
  }
}
