import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { SearchEmailsQuery } from '~/features/content/search/search-emails.query';
import { GetFullSyncStatsQuery } from '~/features/full-sync/get-full-sync-stats.query';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
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

const SearchEmailsOutputSchema = z.object({
  success: z.boolean(),
  message: z.string().optional(),
  results: z.array(SearchEmailResultSchema).optional(),
  status: z.string().optional(),
  syncWarning: z.string().optional(),
});

@Injectable()
export class SearchEmailsTool {
  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly searchEmailsQuery: SearchEmailsQuery,
    private readonly getFullSyncStatsQuery: GetFullSyncStatsQuery,
  ) {}

  @Tool({
    name: 'search_emails',
    title: 'Search Emails',
    description:
      'Search emails semantically with optional structured filters. Returns matched email passages with an id per result.\n\nTo filter by folder, call `list_folders` first to obtain valid folder ids. To filter by category, call `list_categories` first to obtain valid category names. To read the full body of a result, call `open_email_by_id` with the result\'s id. If the response includes a `syncWarning`, call `sync_progress` to check ingestion status — results may be incomplete.',
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
      return subscriptionStatus;
    }

    const results = await this.searchEmailsQuery.run(userProfileTypeId.toString(), input);
    const stats = await this.getFullSyncStatsQuery.run(userProfileTypeId);

    if (stats.state === 'unknown') {
      return {
        success: true,
        syncWarning:
          'Search results may be inaccurate. Ingestion Statistics could not be fetched. Your inbox is a unknown state try to use the tools `remove_inbox_connection` and `reconnect_inbox` to get it into a proper state',
        results,
      };
    }
    if (stats.state === 'running') {
      return {
        success: true,
        syncWarning:
          'Email ingestion is still in progress. Search results may be incomplete and not reflect all emails in the inbox.',
        results,
      };
    }

    return { success: true, results };
  }
}
