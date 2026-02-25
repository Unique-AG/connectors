import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { SearchEmailsInputSchema } from '~/email-sync/content/search/search-conditions.dto';
import { SearchEmailsQuery } from '~/email-sync/content/search/search-emails.query';
import { GetSubscriptionStatusQuery } from '~/email-sync/subscriptions/get-subscription-status.query';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';

const SearchEmailResultSchema = z.object({
  id: z.string(),
  emailId: z.string(),
  folderId: z.string(),
  title: z.string(),
  from: z.string(),
  receivedDateTime: z.string().optional().nullable(),
  text: z.string(),
  url: z.string().optional(),
});

const sucessResponse = z.object({
  success: z.literal(true),
  results: z.array(SearchEmailResultSchema),
});
const errorResponse = z.object({
  success: z.literal(false),
  message: z.string(),
  status: z.string().optional(),
});
const SearchEmailsOutputSchema = z.discriminatedUnion('success', [sucessResponse, errorResponse]);

@Injectable()
export class SearchEmailsTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly searchEmailsQuery: SearchEmailsQuery,
  ) {}

  @Tool({
    name: 'search_emails',
    title: 'Search Emails',
    description:
      'Search emails semantically with optional structured filters (sender, date range, recipients, folder, attachments, categories). Returns matched email passages.',
    parameters: SearchEmailsInputSchema,
    outputSchema: SearchEmailsOutputSchema,
    annotations: {
      title: 'Search Emails',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'search',
      'unique.app/system-prompt':
        'Searches ingested Outlook emails semantically. Use conditions to filter by sender, date, recipient, folder, attachments, or category. Returns matched passages from emails with metadata. Call list_folders first to get folder IDs for directory filtering.',
    },
  })
  @Span()
  public async searchEmails(
    input: z.infer<typeof SearchEmailsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof SearchEmailsOutputSchema>> {
    const userProfileTypeId = extractUserProfileId(request);

    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
    if (!subscriptionStatus.success) {
      this.logger.debug({
        userProfileId: userProfileTypeId.toString(),
        msg: subscriptionStatus.message,
      });
      return subscriptionStatus;
    }

    const results = await this.searchEmailsQuery.run(userProfileTypeId.toString(), input);
    return { success: true, results };
  }
}
