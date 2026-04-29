import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { SearchEmailsQuery } from '~/features/content/search/search-emails.query';
import {
  SearchEmailsMsGraphInputSchema,
  SearchEmailsUnifiedInputSchema,
} from '~/features/content/search/semantic-search-conditions.dto';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { GetFullSyncStatsQuery } from '~/features/sync/full-sync/get-full-sync-stats.query';
import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { META } from './search-emails-tool.meta';
import { SearchBackend } from './semantic-search-emails.query';

const IS_MICROSOFT_GRAPH_BACKEND = isMicrosoftGraphBackend();

const SearchEmailsToolInputSchema = IS_MICROSOFT_GRAPH_BACKEND
  ? SearchEmailsMsGraphInputSchema
  : SearchEmailsUnifiedInputSchema;

const SearchEmailResultSchema = z.object({
  uniqueContentId: z.string().optional(),
  msGraphMessageId: z.string().optional(),
  folderId: z.string(),
  title: z.string(),
  from: z.string(),
  receivedDateTime: z.string().optional().nullable(),
  text: z.string(),
  outlookWebLink: z.string(),
  uniqueContentUrl: z.string().optional(),
  backend: z.nativeEnum(SearchBackend),
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
      'Search emails semantically with optional structured filters. Returns matched email passages with an id per result.\n\nTo filter by folder, call `list_folders` first to obtain valid folder ids. To filter by category, call `list_categories` first to obtain valid category names. To read the full body of a result, call `open_email_by_id` passing `uniqueContentId` (or `msGraphMessageId` if unavailable) as `id`, and `Unique` (or `MsGraph`) as `idType`. If the response includes a `syncWarning`, call `sync_progress` to check ingestion status — results may be incomplete.',
    parameters: SearchEmailsToolInputSchema,
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
    input: z.infer<typeof SearchEmailsToolInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof SearchEmailsOutputSchema>> {
    const userProfileTypeId = extractUserProfileId(request);

    if (!IS_MICROSOFT_GRAPH_BACKEND) {
      const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
      if (!subscriptionStatus.success) {
        return subscriptionStatus;
      }
    }

    const results = await this.searchEmailsQuery.run(userProfileTypeId.toString(), input);

    if (!IS_MICROSOFT_GRAPH_BACKEND) {
      const stats = await this.getFullSyncStatsQuery.run(userProfileTypeId);

      if (stats.state === 'error') {
        return {
          success: true,
          syncWarning:
            'Search results may be inaccurate. Ingestion Statistics could not be fetched. Your inbox is in an unknown state try to use the tools `delete_inbox_data` and `reconnect_inbox` to get it into a proper state',
          results,
        };
      }
      if (stats.state === 'running') {
        return {
          success: true,
          syncWarning:
            'Email ingestion is still in progress. Search results may be incomplete and not reflect all emails in the inbox. The sync process synchronizes newest emails first.',
          results,
        };
      }
    }

    return { success: true, results };
  }
}
