import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { SearchEmailsQuery } from '~/features/content/search/search-emails.query';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { GetFullSyncStatsQuery } from '~/features/sync/full-sync/get-full-sync-stats.query';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { META } from './search-emails-tool.meta';

const SearchEmailResultSchema = z.object({
  id: z.string(),
  emailId: z.string(),
  folderId: z.string(),
  title: z.string(),
  from: z.string(),
  receivedDateTime: z.string().optional().nullable(),
  text: z.string(),
  outlookWebLink: z.string().optional(),
  url: z.string().optional(),
});

const SearchEmailsOutputSchema = z.object({
  success: z.boolean(),
  message: z.string().optional(),
  results: z.array(SearchEmailResultSchema).optional(),
  status: z.string().optional(),
  syncWarning: z.string().optional(),
  searchSummary: z.string().optional(),
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
      "Search emails semantically with optional structured filters. Returns matched email passages with an id per result.\n\nTo filter by folder, call `list_folders` first to obtain valid folder ids. To filter by category, call `list_categories` first to obtain valid category names. To read the full body of a result, call `open_email_by_id` with the result's id. If the response includes a `syncWarning`, call `sync_progress` to check ingestion status — results may be incomplete.",
    parameters: SearchEmailsInputSchema,
    outputSchema: SearchEmailsOutputSchema,
    annotations: {
      title: 'Search Emails',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
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

    const { results, searchSummary } = await this.searchEmailsQuery.run(
      userProfileTypeId.toString(),
      input,
    );
    const stats = await this.getFullSyncStatsQuery.run(userProfileTypeId);

    if (stats.state === 'error') {
      return {
        success: true,
        syncWarning:
          'Search results may be inaccurate. Ingestion Statistics could not be fetched. Your inbox is a unknown state try to use the tools `remove_inbox_connection` and `reconnect_inbox` to get it into a proper state',
        results,
        searchSummary,
      };
    }
    if (stats.state === 'running') {
      return {
        success: true,
        syncWarning:
          'Email ingestion is still in progress. Search results may be incomplete and not reflect all emails in the inbox. The sync process synchronizes newest emails first.',
        results,
        searchSummary,
      };
    }

    return { success: true, results, searchSummary };
  }
}
