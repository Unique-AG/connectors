import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import type { Counter, Histogram } from '@opentelemetry/api';
import Bottleneck from 'bottleneck';
import { sql } from 'drizzle-orm';
import { MetricService, Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import z from 'zod';
import { inboxConfiguration } from '~/db';
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
import { IngestEmailCommand } from '../../mail-ingestion/ingest-email.command';
import { shouldSkipEmail } from '../../mail-ingestion/utils/should-skip-email';
import { FindInboxConfigByVersionQuery } from './find-inbox-config-by-version.query';
import { START_FULL_SYNC_LINK } from './full-sync.command';
import { UpdateInboxConfigByVersionCommand } from './update-inbox-config-by-version.command';
import assert from 'node:assert';

export type BatchResult =
  | { outcome: 'batch-uploaded' }
  | { outcome: 'completed' }
  | { outcome: 'version-mismatch' }
  | { outcome: 'missing-full-sync-next-link' };

const PAGE_LIMIT = 100;
const MAX_RETRIES = 3;
const BASE_BACKOFF_MS = 500;

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

    // ── Batch processing algorithm ──────────────────────────────────────
    // This loop pages through the user's mailbox via Graph API and ingests
    // messages one by one. It is designed to be **pausable**, **resumable**,
    // and **fair across users**:
    //
    //  1. Fetch a page of messages using `nextLink` (or the initial query).
    //     If the nextLink has expired (410), fall back to a fresh first-page
    //     query filtered by `oldestCreatedDateTime` and reset `batchIndex`
    //     to 0 so the page is reprocessed from the start.
    //
    //  2. Iterate over the page starting at `batchIndex` (the resume point).
    //     For each message: skip, ingest, or record failure. After every
    //     single message the current `batchIndex` is persisted so a crash
    //     or restart resumes exactly where we left off.
    //
    //  3. Once `PAGE_LIMIT` messages have been uploaded, return
    //     `batch-uploaded` so the scheduler can give other users a turn
    //     (fairness). The caller will re-enqueue this user for the next batch.
    //
    //  4. When `batchIndex` reaches the end of a page (reset to 0), advance
    //     to the next page via `nextPageLink`. Watermarks (oldest/newest
    //     `createdDateTime`) are saved after every page for progress tracking.
    //
    //  5. If there are no more pages, return `completed`.
    //
    // Every DB write is version-guarded: if the version has changed (e.g.
    // the user triggered a fresh sync), we bail out with `version-mismatch`
    // immediately so we don't overwrite newer state.
    // ─────────────────────────────────────────────────────────────────────

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

      let i = iterationInfo.batchIndex;
      for (; i < page.length && iterationInfo.uploaded < PAGE_LIMIT; i++) {
        const message = page[i];
        if (!message) {
          continue;
        }

        const processMessageResult = await this.processMessage({
          message,
          filters,
          userProfileId,
          version,
        });

        if (processMessageResult === 'version-mismatch') {
          this.logger.log({
            ...iterationInfo,
            messageIndex: i,
            msg: 'Version mismatch during message processing',
          });
          return { outcome: 'version-mismatch' };
        } else if (processMessageResult === 'ingested') {
          iterationInfo.uploaded++;
        } else if (processMessageResult === 'skipped') {
          iterationInfo.skipped++;
        } else {
          iterationInfo.failed++;
        }

        iterationInfo.batchIndex = i + 1;
        if (iterationInfo.batchIndex === page.length) {
          iterationInfo.batchIndex = 0;
        }
        const timestamps = !message.createdDateTime
          ? {}
          : {
              newestCreatedDateTime: sql`GREATEST(COALESCE(${inboxConfiguration.newestCreatedDateTime}, '-infinity'::timestamptz), ${new Date(message.createdDateTime)})`,
              oldestCreatedDateTime: sql`LEAST(COALESCE(${inboxConfiguration.oldestCreatedDateTime}, 'infinity'::timestamptz), ${new Date(message.createdDateTime)})`,
            };
        const isIndexSaved = await this.updateByVersionCommand.run(userProfileId, version, {
          ...timestamps,
          fullSyncBatchIndex: iterationInfo.batchIndex,
        });
        if (!isIndexSaved) {
          return { outcome: 'version-mismatch' };
        }
      }

      // If the page shrank (e.g. messages deleted between fetches) and our
      // saved batchIndex now exceeds the page size, the for-loop above never
      // ran. Treat the page as fully consumed to avoid an infinite loop.
      if (iterationInfo.batchIndex >= page.length) {
        this.logger.warn({
          ...iterationInfo,
          msg: 'batchIndex exceeds page size (page shrank), treating page as fully consumed',
        });
        iterationInfo.batchIndex = 0;
      }

      const pageWasFullyProcessed = iterationInfo.batchIndex === 0;

      if (pageWasFullyProcessed) {
        // Batch is completed we move to next page.
        iterationInfo.nextLink = nextPageLink ?? null;
      }

      const indexesSaved = await this.updateByVersionCommand.run(userProfileId, version, {
        fullSyncBatchIndex: iterationInfo.batchIndex,
        fullSyncNextLink: iterationInfo.nextLink,
      });
      if (!indexesSaved) {
        return { outcome: 'version-mismatch' };
      }

      if (iterationInfo.nextLink && iterationInfo.uploaded >= PAGE_LIMIT) {
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
      .top(PAGE_LIMIT)
      .get();
  }

  @Span()
  private async processMessage({
    message,
    filters,
    userProfileId,
    version,
  }: {
    message: FullSyncBatchGraphMessage;
    filters: InboxConfigurationMailFilters;
    userProfileId: string;
    version: string;
  }): Promise<'ingested' | 'skipped' | 'failed' | 'version-mismatch'> {
    const skipResult = shouldSkipEmail(message, filters, { userProfileId });
    if (skipResult.skip) {
      this.messagesProcessed.add(1, { outcome: 'skipped' });
      const saved = await this.updateByVersionCommand.run(userProfileId, version, {
        fullSyncSkipped: sql`${inboxConfiguration.fullSyncSkipped} + 1`,
        fullSyncHeartbeatAt: sql`NOW()`,
      });
      return saved ? 'skipped' : 'version-mismatch';
    }

    const ingested = await recordInHistogram({
      histogram: this.ingestionDuration,
      attributes: (ingested) => ({ outcome: ingested ? 'success' : 'failure' }),
      fn: () => this.ingestWithRetries(userProfileId, message.id),
    });

    if (ingested) {
      this.messagesProcessed.add(1, { outcome: 'ingested' });
      const saved = await this.updateByVersionCommand.run(userProfileId, version, {
        fullSyncScheduledForIngestion: sql`${inboxConfiguration.fullSyncScheduledForIngestion} + 1`,
        fullSyncHeartbeatAt: sql`NOW()`,
      });
      return saved ? 'ingested' : 'version-mismatch';
    }

    this.messagesProcessed.add(1, { outcome: 'failed' });
    this.logger.warn({
      userProfileId,
      messageId: message.id,
      msg: 'Message ingestion failed after retries',
    });
    const saved = await this.updateByVersionCommand.run(userProfileId, version, {
      fullSyncFailedToUploadForIngestion: sql`${inboxConfiguration.fullSyncFailedToUploadForIngestion} + 1`,
      fullSyncHeartbeatAt: sql`NOW()`,
    });
    return saved ? 'failed' : 'version-mismatch';
  }

  private async ingestWithRetries(userProfileId: string, messageId: string): Promise<boolean> {
    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
      try {
        await this.ingestEmailCommand.run({ userProfileId, messageId });
        return true;
      } catch (error) {
        // Bottleneck errors mean the rate limiter is overwhelmed or stopped.
        // Retrying is pointless — re-throw so the sync transitions to failed
        // state and the scheduler can pick it up later.
        if (error instanceof Bottleneck.BottleneckError) {
          throw error;
        }

        this.logger.warn({
          err: error,
          userProfileId,
          messageId,
          attempt,
          msg: `Ingestion attempt ${attempt}/${MAX_RETRIES} failed`,
        });

        if (attempt < MAX_RETRIES) {
          await this.sleep(BASE_BACKOFF_MS * 2 ** (attempt - 1));
        }
      }
    }

    this.logger.error({
      userProfileId,
      messageId,
      msg: `Ingestion failed after ${MAX_RETRIES} retries`,
    });
    return false;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
