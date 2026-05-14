import assert from 'node:assert';
import { UniqueApiClient, UniqueFile } from '@unique-ag/unique-api';
import { createSmeared } from '@unique-ag/utils';
import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import z from 'zod';
import { inboxConfigurations, UserProfile } from '~/db';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { getUniqueKeyForMessage } from '~/features/process-email/utils/get-unique-key-for-message';
import { NewTrace, traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { computeRetentionCutoffDate } from '~/utils/date/compute-retention-cutoff-date';
import { greatestFrom } from '~/utils/greatest-from';
import { leastFrom } from '~/utils/least-from';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { SyncMetricsService } from '~/features/metrics/sync-metrics.service';
import {
  GraphMessageFields,
  graphMessagesResponseSchema,
} from '../../process-email/dtos/microsoft-graph.dtos';
import {
  MessageIngestionResult,
  ProcessEmailCommand,
  ProcessEmailCommandInput,
} from '../../process-email/process-email.command';
import { FindInboxConfigByVersionQuery } from './find-inbox-config-by-version.query';
import { START_FULL_SYNC_LINK } from './full-sync.command';
import type { BatchResult } from './full-sync.types';
import {
  InboxConfigVersionedUpdate,
  UpdateInboxConfigByVersionCommand,
} from './update-inbox-config-by-version.command';

const GRAPH_PAGE_LIMIT = 100;
// We aim to upload 100 messages and we do not want to upload twice as much when a couple failed.
const MAX_MESSAGES_PROCESSED_PAGE_LIMIT = GRAPH_PAGE_LIMIT - 50;

type PossibleIngestionResults = MessageIngestionResult | 'failed';

@Injectable()
export class ProcessFullSyncBatchCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly processEmailCommand: ProcessEmailCommand,
    private readonly updateByVersionCommand: UpdateInboxConfigByVersionCommand,
    private readonly findConfigByVersion: FindInboxConfigByVersionQuery,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly metrics: SyncMetricsService,
  ) {}

  @NewTrace('process-full-sync-batch')
  public async run({
    userProfile,
    version,
  }: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    version: string;
  }): Promise<BatchResult> {
    traceAttrs({ userProfileId: userProfile.id, version });

    const config = await this.findConfigByVersion.run(userProfile.id, version);
    if (isNullish(config)) {
      this.logger.warn({
        userProfileId: userProfile.id,
        version,
        msg: 'Version mismatch on config load',
      });
      return { outcome: 'version-mismatch' };
    }
    if (!config.fullSyncNextLink) {
      this.logger.warn({ userProfileId: userProfile.id, version, msg: 'Missing fullSyncNextLink' });
      return { outcome: 'missing-full-sync-next-link' };
    }

    const { fullSyncNextLink, fullSyncBatchIndex } = config;
    const filters = inboxConfigurationMailFilters.parse(config.filters);
    const client = this.graphClientFactory.createClientForUser(userProfile.id);

    this.logger.log({
      userProfileId: userProfile.id,
      version,
      resumeFromIndex: fullSyncBatchIndex,
      isFirstPage: fullSyncNextLink === START_FULL_SYNC_LINK,
      msg: 'Batch config loaded',
    });

    // ── Batch processing algorithm ───────────────────────────────────────────────────────────
    // Pages through the user's mailbox via Graph API and ingests messages one by one. Designed
    // to be pausable, resumable, and fair across users:
    //
    //  1. Fetch a page using `nextLink` (or initial query). On 410 (expired link): fall back
    //     to a fresh query filtered by `oldestReceivedEmailDateTime`, reset `batchIndex`.
    //
    //  2. Iterate from `batchIndex` (resume point). For each message: skip, ingest, or record
    //     failure. Persist `batchIndex`, watermarks, and counters after every message for crash
    //     recovery.
    //
    //  3. After processing a full page, if (uploaded + failed) reached the batch limit and more
    //     pages remain, return `batch-uploaded` so the scheduler can give other users a turn.
    //
    //  4. At page end (batchIndex reset to 0), save `nextLink` to advance to the next page.
    //
    //  5. No more pages (or empty page) → return `completed`.
    //
    // All DB writes are version-guarded: bail with `version-mismatch` if the version changed
    // (e.g. user triggered a fresh sync) to avoid overwriting newer state.
    // ─────────────────────────────────────────────────────────────────────────────────────────

    // We need this intermediate object so that typescript does not complain because { nextLink: string | null }.
    const iterationInfo = {
      userProfileId: userProfile.id,
      version,
      batchIndex: config.fullSyncBatchIndex,
      uploaded: 0,
      skipped: 0,
      failed: 0,
      pageNumber: 0,
      pageSize: 0,
      // We do type casting because during while it will become null.
      nextLink: fullSyncNextLink as string | null,
    };

    while (iterationInfo.nextLink) {
      iterationInfo.pageNumber++;
      const fetchPageResult = await this.fetchPage({
        client,
        nextLink: iterationInfo.nextLink,
        filters,
        userProfileId: iterationInfo.userProfileId,
        version,
      });

      if (fetchPageResult.status === 'version-mismatch') {
        return { outcome: 'version-mismatch' };
      }
      const {
        data: { value: page, '@odata.nextLink': nextPageLink },
        resetBatchIndex,
      } = fetchPageResult;
      // We could not use the nextLink this means the batchIndex should be reset to 0 and page needs to be reprocessed
      // because next link expired.
      if (resetBatchIndex) {
        iterationInfo.batchIndex = 0;
      }

      iterationInfo.pageSize = page.length;
      if (page.length === 0) {
        this.logger.log({
          userProfileId: iterationInfo.userProfileId,
          version: iterationInfo.version,
          pageNumber: iterationInfo.pageNumber,
          msg: 'Empty page, ending sync',
        });
        break;
      }

      const messages = page.slice(iterationInfo.batchIndex);

      const fileKeys = messages.map((item) =>
        getUniqueKeyForMessage({ userEmail: userProfile.email, messageId: item.id }),
      );
      const uniqueFiles = await this.uniqueApi.files.getByKeys(fileKeys);
      const uniqueFilesHashMap = uniqueFiles.reduce<Record<string, UniqueFile>>((acc, file) => {
        acc[file.key] = file;
        return acc;
      }, {});

      for (const message of messages) {
        const fileKey = getUniqueKeyForMessage({
          userEmail: userProfile.email,
          messageId: message.id,
        });
        const processMessageResult = await this.processMessage({
          user: {
            profileId: userProfile.id,
            providerId: userProfile.providerUserId,
            email: createSmeared(userProfile.email),
          },
          client,
          file: uniqueFilesHashMap[fileKey] ?? null,
          fileKey,
          filters,
          graphMessage: message,
        });

        const updateObject: InboxConfigVersionedUpdate = {};
        if (processMessageResult === 'ingested') {
          iterationInfo.uploaded++;
          updateObject.fullSyncScheduledForIngestion = sql`${inboxConfigurations.fullSyncScheduledForIngestion} + 1`;
        } else if (processMessageResult === 'skipped') {
          iterationInfo.skipped++;
          updateObject.fullSyncSkipped = sql`${inboxConfigurations.fullSyncSkipped} + 1`;
        } else {
          iterationInfo.failed++;
          updateObject.fullSyncFailedToUploadForIngestion = sql`${inboxConfigurations.fullSyncFailedToUploadForIngestion} + 1`;
        }

        iterationInfo.batchIndex++;
        const receivedDateTime = new Date(message.receivedDateTime);
        updateObject.newestReceivedEmailDateTime = greatestFrom(
          inboxConfigurations.newestReceivedEmailDateTime,
          receivedDateTime,
        );
        updateObject.oldestReceivedEmailDateTime = leastFrom(
          inboxConfigurations.oldestReceivedEmailDateTime,
          receivedDateTime,
        );
        const isIndexSaved = await this.updateByVersionCommand.run(
          iterationInfo.userProfileId,
          version,
          {
            ...updateObject,
            fullSyncBatchIndex: iterationInfo.batchIndex,
            fullSyncHeartbeatAt: sql`NOW()`,
          },
        );
        if (!isIndexSaved) {
          return { outcome: 'version-mismatch' };
        }
      }

      this.logger.log({
        userProfileId: iterationInfo.userProfileId,
        version: iterationInfo.version,
        pageNumber: iterationInfo.pageNumber,
        pageSize: iterationInfo.pageSize,
        uploaded: iterationInfo.uploaded,
        skipped: iterationInfo.skipped,
        failed: iterationInfo.failed,
        msg: 'Page processed',
      });

      iterationInfo.batchIndex = 0;
      iterationInfo.nextLink = nextPageLink ?? null;

      const indexesSaved = await this.updateByVersionCommand.run(
        iterationInfo.userProfileId,
        version,
        {
          fullSyncBatchIndex: iterationInfo.batchIndex,
          fullSyncNextLink: iterationInfo.nextLink,
        },
      );
      if (!indexesSaved) {
        return { outcome: 'version-mismatch' };
      }

      if (
        iterationInfo.nextLink &&
        // We consider both uploaded and failed because if ingestion is down we do not want to run through
        // all pages at once, skipped is not important cause we will skip them anyway.
        iterationInfo.uploaded + iterationInfo.failed >= MAX_MESSAGES_PROCESSED_PAGE_LIMIT
      ) {
        traceEvent('batch-uploaded');
        this.logger.log({
          userProfileId: iterationInfo.userProfileId,
          version: iterationInfo.version,
          uploaded: iterationInfo.uploaded,
          skipped: iterationInfo.skipped,
          failed: iterationInfo.failed,
          pageNumber: iterationInfo.pageNumber,
          msg: 'Batch yielded, more pages remain',
        });
        return { outcome: 'batch-uploaded' };
      }
    }

    traceEvent('completed');
    this.logger.log({
      userProfileId: iterationInfo.userProfileId,
      version: iterationInfo.version,
      uploaded: iterationInfo.uploaded,
      skipped: iterationInfo.skipped,
      failed: iterationInfo.failed,
      pageNumber: iterationInfo.pageNumber,
      msg: 'Full sync batch completed',
    });
    return { outcome: 'completed' };
  }

  @Span()
  private async fetchPage({
    client,
    nextLink,
    filters,
    userProfileId,
    version,
  }: {
    client: Client;
    nextLink: string;
    filters: InboxConfigurationMailFilters;
    userProfileId: string;
    version: string;
  }): Promise<
    | {
        status: 'proceed';
        resetBatchIndex: boolean;
        data: z.infer<typeof graphMessagesResponseSchema>;
      }
    | {
        status: 'version-mismatch';
      }
  > {
    const conditions = [
      `receivedDateTime ge ${computeRetentionCutoffDate(filters.retentionWindowInDays).toISOString()}`,
    ];

    if (nextLink === START_FULL_SYNC_LINK) {
      const raw = await this.metrics.measureGraphPage(() => this.fetchFirstPage(client, conditions), 'first');
      return {
        status: 'proceed',
        resetBatchIndex: false,
        data: graphMessagesResponseSchema.parse(raw),
      };
    }

    try {
      const raw = await this.metrics.measureGraphPage(
        () => client.api(nextLink).header('Prefer', 'IdType="ImmutableId"').get(),
        'next',
      );
      return {
        status: 'proceed',
        resetBatchIndex: false,
        data: graphMessagesResponseSchema.parse(raw),
      };
    } catch (error) {
      const isExpiredNextLink = error instanceof GraphError && error.statusCode === 410;
      if (!isExpiredNextLink) {
        throw error;
      }
      this.logger.warn({
        userProfileId,
        msg: 'Graph API nextLink expired (410), falling back to first page applying the filters',
        err: error,
      });
    }

    // This is the case where next link is expired => Happy path ended in the try { } catch {} block.
    const freshConfig = await this.findConfigByVersion.run(userProfileId, version);
    if (isNullish(freshConfig)) {
      return { status: 'version-mismatch' };
    }
    assert.ok(
      freshConfig.oldestReceivedEmailDateTime,
      `Created date time is null durring expired next link`,
    );
    conditions.push(`receivedDateTime le ${freshConfig.oldestReceivedEmailDateTime.toISOString()}`);
    const raw = await this.metrics.measureGraphPage(() => this.fetchFirstPage(client, conditions), 'next');
    return {
      status: 'proceed',
      resetBatchIndex: true,
      data: graphMessagesResponseSchema.parse(raw),
    };
  }

  private async fetchFirstPage(client: Client, conditions: string[]): Promise<unknown> {
    return client
      .api('me/messages')
      .header('Prefer', 'IdType="ImmutableId"')
      .select(GraphMessageFields)
      .filter(conditions.join(' and '))
      .orderby('receivedDateTime desc')
      .top(GRAPH_PAGE_LIMIT)
      .get();
  }

  @Span()
  private async processMessage(
    input: ProcessEmailCommandInput,
  ): Promise<'ingested' | 'skipped' | 'failed'> {
    const processingResult = await this.metrics.countFullSyncMessage(
      () => this.metrics.measureEmailProcessing(() => this.processEmailCommand.run(input)),
    );

    if (processingResult === 'failed') {
      this.logger.warn({
        userProfileId: input.user.profileId,
        messageId: input.graphMessage.id,
        msg: 'Message ingestion failed after retries',
      });
    }

    const mapToOurResult: Record<PossibleIngestionResults, 'ingested' | 'skipped' | 'failed'> = {
      ingested: `ingested`,
      skipped: `skipped`,
      'skipped-content-unchanged-already-ingested': `ingested`,
      'content-updated': `ingested`,
      failed: `failed`,
    };
    return mapToOurResult[processingResult];
  }
}
