import assert from 'node:assert';
import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import type { Counter, Histogram } from '@opentelemetry/api';
import { sql } from 'drizzle-orm';
import { MetricService, Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import z from 'zod';
import { inboxConfigurations } from '~/db';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { recordInHistogram } from '~/utils/record-in-histogram';
import {
  FullSyncBatchGraphMessage,
  FullSyncBatchGraphMessageFields,
  fullSyncBatchGraphMessageResponseSchema,
} from '../../mail-ingestion/dtos/microsoft-graph.dtos';
import {
  IngestEmailCommand,
  MessageIngestionResult,
} from '../../mail-ingestion/ingest-email.command';
import { shouldSkipEmail } from '../../mail-ingestion/utils/should-skip-email';
import { FindInboxConfigByVersionQuery } from './find-inbox-config-by-version.query';
import { START_FULL_SYNC_LINK } from './full-sync.command';
import {
  InboxConfigVersionedUpdate,
  UpdateInboxConfigByVersionCommand,
} from './update-inbox-config-by-version.command';

export type BatchResult =
  | { outcome: 'batch-uploaded' }
  | { outcome: 'completed' }
  | { outcome: 'version-mismatch' }
  | { outcome: 'missing-full-sync-next-link' };

const GRAPH_PAGE_LIMIT = 100;
// We aim to upload 100 messages and we do not want to upload twice as much when a couple failed.
const MAX_MESSAGES_PROCESSED_PAGE_LIMIT = GRAPH_PAGE_LIMIT - 50;

type PossibleIngestionResults = MessageIngestionResult | 'failed';

@Injectable()
export class ProcessFullSyncBatchCommand {
  private readonly logger = new Logger(this.constructor.name);

  private readonly graphPageDuration: Histogram;
  private readonly ingestionDuration: Histogram;
  private readonly messagesProcessed: Counter;

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly ingestEmailCommand: IngestEmailCommand,
    private readonly updateByVersionCommand: UpdateInboxConfigByVersionCommand,
    private readonly findConfigByVersion: FindInboxConfigByVersionQuery,
    metricService: MetricService,
  ) {
    this.graphPageDuration = metricService.getHistogram('full_sync_graph_page_duration_seconds', {
      description: 'Duration of Graph API page fetch during full sync',
    });
    this.ingestionDuration = metricService.getHistogram('full_sync_ingestion_duration_seconds', {
      description: 'Duration of single message ingestion during full sync (including retries)',
    });
    this.messagesProcessed = metricService.getCounter('full_sync_messages_processed_total', {
      description: 'Total messages processed during full sync',
    });
  }

  @Span()
  public async run({
    userProfileId,
    version,
  }: {
    userProfileId: string;
    version: string;
  }): Promise<BatchResult> {
    traceAttrs({ userProfileId, version });

    this.logger.log({ userProfileId, version, msg: 'Starting batch processing' });

    const config = await this.findConfigByVersion.run(userProfileId, version);
    if (isNullish(config)) {
      this.logger.log({ userProfileId, version, msg: 'Version mismatch on config load' });
      return { outcome: 'version-mismatch' };
    }
    if (!config.fullSyncNextLink) {
      this.logger.log({ userProfileId, version, msg: 'Missing fullSyncNextLink' });
      return { outcome: 'missing-full-sync-next-link' };
    }

    const { fullSyncNextLink, fullSyncBatchIndex } = config;
    const filters = inboxConfigurationMailFilters.parse(config.filters);
    const client = this.graphClientFactory.createClientForUser(userProfileId);

    this.logger.log({
      userProfileId,
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
    //     to a fresh query filtered by `oldestCreatedDateTime`, reset `batchIndex`.
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
      userProfileId,
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
        userProfileId,
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
        this.logger.log({ ...iterationInfo, msg: 'Empty page, ending' });
        break;
      }

      this.logger.log({
        ...iterationInfo,
        msg: 'Graph API page fetched',
      });

      for (const message of page.slice(iterationInfo.batchIndex)) {
        const processMessageResult = await this.processMessage({
          message,
          filters,
          userProfileId,
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
        updateObject.newestCreatedDateTime = sql`GREATEST(${inboxConfigurations.newestCreatedDateTime}, ${new Date(message.createdDateTime)})`;
        updateObject.oldestCreatedDateTime = sql`LEAST(${inboxConfigurations.oldestCreatedDateTime}, ${new Date(message.createdDateTime)})`;
        const isIndexSaved = await this.updateByVersionCommand.run(userProfileId, version, {
          ...updateObject,
          fullSyncBatchIndex: iterationInfo.batchIndex,
          fullSyncHeartbeatAt: sql`NOW()`,
        });
        if (!isIndexSaved) {
          return { outcome: 'version-mismatch' };
        }
      }

      iterationInfo.batchIndex = 0;
      iterationInfo.nextLink = nextPageLink ?? null;

      const indexesSaved = await this.updateByVersionCommand.run(userProfileId, version, {
        fullSyncBatchIndex: iterationInfo.batchIndex,
        fullSyncNextLink: iterationInfo.nextLink,
      });
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
        return { outcome: 'batch-uploaded' };
      }
    }

    traceEvent('completed');
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
        data: z.infer<typeof fullSyncBatchGraphMessageResponseSchema>;
      }
    | {
        status: 'version-mismatch';
      }
  > {
    const conditions = [`createdDateTime gt ${filters.ignoredBefore.toISOString()}`];

    if (nextLink === START_FULL_SYNC_LINK) {
      const raw = await recordInHistogram({
        histogram: this.graphPageDuration,
        attributes: { page_type: 'first' },
        fn: () => this.fetchFirstPage(client, conditions),
      });
      return {
        status: 'proceed',
        resetBatchIndex: false,
        data: fullSyncBatchGraphMessageResponseSchema.parse(raw),
      };
    }

    try {
      const raw = await recordInHistogram({
        histogram: this.graphPageDuration,
        attributes: { page_type: 'next' },
        fn: () => client.api(nextLink).header('Prefer', 'IdType="ImmutableId"').get(),
      });
      return {
        status: 'proceed',
        resetBatchIndex: false,
        data: fullSyncBatchGraphMessageResponseSchema.parse(raw),
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
      freshConfig.oldestCreatedDateTime,
      `Created date time is null durring expired next link`,
    );
    conditions.push(`createdDateTime le ${freshConfig.oldestCreatedDateTime.toISOString()}`);
    const raw = await recordInHistogram({
      histogram: this.graphPageDuration,
      attributes: { page_type: 'next' },
      fn: () => this.fetchFirstPage(client, conditions),
    });
    return {
      status: 'proceed',
      resetBatchIndex: true,
      data: fullSyncBatchGraphMessageResponseSchema.parse(raw),
    };
  }

  private async fetchFirstPage(client: Client, conditions: string[]): Promise<unknown> {
    return client
      .api('me/messages')
      .header('Prefer', 'IdType="ImmutableId"')
      .select(FullSyncBatchGraphMessageFields)
      .filter(conditions.join(' and '))
      .orderby('createdDateTime desc')
      .top(GRAPH_PAGE_LIMIT)
      .get();
  }

  @Span()
  private async processMessage({
    message,
    filters,
    userProfileId,
  }: {
    message: FullSyncBatchGraphMessage;
    filters: InboxConfigurationMailFilters;
    userProfileId: string;
  }): Promise<'ingested' | 'skipped' | 'failed'> {
    const skipResult = shouldSkipEmail(message, filters, { userProfileId });
    if (skipResult.skip) {
      this.messagesProcessed.add(1, { outcome: 'skipped' });
      return 'skipped';
    }

    const ingestionResult = await recordInHistogram({
      histogram: this.ingestionDuration,
      attributes: (result) => ({ outcome: result === 'failed' ? 'failure' : 'success' }),
      fn: () => this.ingestEmailCommand.run({ userProfileId, messageId: message.id }),
    });

    const mapToOurResult: Record<PossibleIngestionResults, 'ingested' | 'skipped' | 'failed'> = {
      ingested: `ingested`,
      skipped: `skipped`,
      'skipped-content-unchanged-already-ingested': `ingested`,
      'metadata-updated': `ingested`,
      failed: `failed`,
    };

    if (ingestionResult === 'failed') {
      this.logger.warn({
        userProfileId,
        messageId: message.id,
        msg: 'Message ingestion failed after retries',
      });
    }
    const outcome = mapToOurResult[ingestionResult];
    this.messagesProcessed.add(1, { outcome });

    return outcome;
  }
}
