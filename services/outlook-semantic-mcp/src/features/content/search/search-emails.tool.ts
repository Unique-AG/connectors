import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { IngestionState } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import * as z from 'zod';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { SearchEmailsQuery } from '~/features/content/search/search-emails.query';
import { GetFullSyncStatsQuery } from '~/features/full-sync/get-full-sync-stats.query';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
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

const INCOMPLETE_INGESTION_STATES = new Set([
  IngestionState.Queued,
  IngestionState.IngestionChunking,
  IngestionState.IngestionEmbedding,
  IngestionState.IngestionReading,
  IngestionState.MetadataValidation,
  IngestionState.CheckingIntegrity,
  IngestionState.MalwareScanning,
  IngestionState.Retrying,
  IngestionState.ReEmbedding,
  IngestionState.ReIngesting,
  IngestionState.RebuildingMetadata,
]);

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
      return subscriptionStatus;
    }

    const results = await this.searchEmailsQuery.run(userProfileTypeId.toString(), input);

    const syncWarningResult = await this.buildSyncWarning(userProfileTypeId);

    return { success: true, ...syncWarningResult, results };
  }

  private async buildSyncWarning(
    userProfileTypeId: UserProfileTypeID,
  ): Promise<{ syncWarning?: string }> {
    const config = await this.getFullSyncStatsQuery.run(userProfileTypeId);
    if (isNullish(config.syncStats) && isNullish(config.ingestionStats)) {
      return {
        syncWarning: `Could not fetch email ingestion statistics. Search results may be incomplete and not reflect all emails in the inbox.`,
      };
    }

    const incompleteIngestionWarning = {
      syncWarning:
        'Email ingestion is still in progress. Search results may be incomplete and not reflect all emails in the inbox.',
    };

    if (config.syncStats) {
      const isSyncRunning = config.syncStats.state === 'running';
      const hasUnprocessedMessages =
        config.syncStats.messages.queuedForSync !== null &&
        config.syncStats.messages.processed !== null &&
        config.syncStats.messages.processed < config.syncStats.messages.queuedForSync;

      if (isSyncRunning || hasUnprocessedMessages) {
        return incompleteIngestionWarning;
      }
    }

    if (config.ingestionStats) {
      const hasPendingItems = Object.entries(config.ingestionStats).some(
        ([state, count]) =>
          INCOMPLETE_INGESTION_STATES.has(state as IngestionState) && (count ?? 0) > 0,
      );

      if (hasPendingItems) {
        return incompleteIngestionWarning;
      }
    }

    return {};
  }
}
