import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import {
  SearchEmailsMsGraphInputSchema,
  SearchEmailsUnifiedInputSchema,
} from '~/features/content/search/search-conditions.dto';
import { SearchEmailsQuery } from '~/features/content/search/search-emails.query';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { GetFullSyncStatsQuery } from '~/features/sync/full-sync/get-full-sync-stats.query';
import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { SearchEmailsOutputSchema, SearchEmailsToolOutput } from './search-emails-output.schema';
import { META_MS_GRAPH, META_UNIQUE_AND_MS_GRAPH } from './search-emails-tool.meta';

const SearchEmailsToolInputSchema = isMicrosoftGraphBackend()
  ? SearchEmailsMsGraphInputSchema
  : SearchEmailsUnifiedInputSchema;

const PAGING_DESCRIPTION =
  'Results come in pages. Every entry in `pages` is one backend request (named by its query, mailbox and folder) with its own status and `cursorId`. ' +
  'Every mailbox and folder is searched on the first call. When a call fans out to many of them, each first page is smaller and the rest is reached through its `cursorId`. ' +
  'When `hasMore` is true, call `fetch_next_search_pages` with the `cursorId`s to get the next pages — never re-run the same search to get more results.';

const OPEN_EMAIL_DESCRIPTION =
  'Each result carries only partial content in `text`, never the full email. ' +
  'To read an email, call `open_email` with the `openEmailParams` object from that result — do this whenever `text` does not clearly answer the question.';

const SearchEmailsToolDescription = isMicrosoftGraphBackend()
  ? [
      'Search emails using Microsoft Graph KQL queries across your own and delegated mailboxes. Results are sorted by sent date, newest first.',
      `${OPEN_EMAIL_DESCRIPTION} Here \`text\` is a short preview of the body (about 255 characters).`,
      `${PAGING_DESCRIPTION} Each KQL query runs once per mailbox (and per folder in \`directories\`), so one query can produce several \`pages\` entries.`,
      'If the response includes `searchNotes`, display them to the user after results.',
    ].join('\n\n')
  : [
      'Search emails semantically with optional structured filters, combined with Microsoft Graph KQL keyword search.',
      `${OPEN_EMAIL_DESCRIPTION} Here \`text\` holds the matched passages and/or a short preview of the body.`,
      PAGING_DESCRIPTION,
      'To filter by a well-known folder (Inbox, Sent Items, Drafts, etc.) pass the name directly in `directories` — no need to call `list_mailboxes_and_directories`. For custom folders, call `list_mailboxes_and_directories` first to get the folder id. To filter by category, call `list_categories` first to obtain valid category names. If the response includes a `syncWarning`, call `sync_progress` to check ingestion status — results may be incomplete. If the response includes `searchNotes`, display them to the user after results.',
    ].join('\n\n');

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
    description: SearchEmailsToolDescription,
    parameters: SearchEmailsToolInputSchema,
    outputSchema: SearchEmailsOutputSchema,
    annotations: {
      title: 'Search Emails',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: isMicrosoftGraphBackend() ? META_MS_GRAPH : META_UNIQUE_AND_MS_GRAPH,
  })
  @Span()
  public async searchEmails(
    input: z.infer<typeof SearchEmailsToolInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<SearchEmailsToolOutput> {
    const userProfileTypeId = extractUserProfileId(request);

    if (!isMicrosoftGraphBackend()) {
      const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
      if (!subscriptionStatus.success) {
        return subscriptionStatus;
      }
    }

    const { results, pages, hasMore, searchSummary } = await this.searchEmailsQuery.run(
      userProfileTypeId,
      input,
    );

    if (!isMicrosoftGraphBackend()) {
      const stats = await this.getFullSyncStatsQuery.run(userProfileTypeId);

      let syncWarning: string | undefined;
      if (stats.state === 'error' || stats.state === 'running') {
        syncWarning = `Your mailbox is still being indexed — searching through your emails will improve over time.`;
      }
      return {
        success: true,
        syncWarning,
        searchNotes: searchSummary,
        results,
        hasMore,
        pages,
      };
    }

    return { success: true, results, hasMore, pages, searchNotes: searchSummary };
  }
}
