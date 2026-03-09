import { IngestionState, type UniqueApiClient } from '@unique-ag/unique-api';
import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, type DrizzleDatabase, inboxConfiguration, userProfiles } from '~/db';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { SearchEmailsQuery } from '~/features/content/search/search-emails.query';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { getRootScopePathForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
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

const INCOMPLETE_INGESTION_WARNING =
  'Email ingestion is still in progress. Search results may be incomplete and not reflect all emails in the inbox.';

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
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
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
      return subscriptionStatus;
    }

    const results = await this.searchEmailsQuery.run(userProfileTypeId.toString(), input);

    const syncWarning = await this.buildSyncWarning(userProfileTypeId.toString());

    return { success: true, results, ...( syncWarning !== undefined && { syncWarning }) };
  }

  private async buildSyncWarning(userProfileId: string): Promise<string | undefined> {
    try {
      const config = await this.db.query.inboxConfiguration.findFirst({
        where: eq(inboxConfiguration.userProfileId, userProfileId),
      });

      if (!config) {
        return undefined;
      }

      const isSyncRunning = config.syncState === 'running';
      const hasUnprocessedMessages =
        config.messagesQueuedForSync !== null &&
        config.messagesProcessed !== null &&
        config.messagesProcessed < config.messagesQueuedForSync;

      if (isSyncRunning || hasUnprocessedMessages) {
        return INCOMPLETE_INGESTION_WARNING;
      }

      const userProfile = await this.db.query.userProfiles.findFirst({
        where: eq(userProfiles.id, userProfileId),
      });

      if (!userProfile?.email) {
        return undefined;
      }

      const rootScopePath = getRootScopePathForUser(userProfile.email);
      const ingestionStats = await this.uniqueApi.content.getIngestionStats(rootScopePath);

      const hasPendingItems = Object.entries(ingestionStats).some(
        ([state, count]) =>
          INCOMPLETE_INGESTION_STATES.has(state as IngestionState) && (count ?? 0) > 0,
      );

      if (hasPendingItems) {
        return INCOMPLETE_INGESTION_WARNING;
      }
    } catch (error) {
      this.logger.warn({ userProfileId, msg: 'Failed to build sync warning', error });
    }

    return undefined;
  }
}
