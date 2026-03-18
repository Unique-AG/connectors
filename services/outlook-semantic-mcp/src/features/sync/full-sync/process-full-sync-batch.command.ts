import { GraphError } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import type { Counter, Histogram } from '@opentelemetry/api';
import { sql } from 'drizzle-orm';
import { MetricService, Span } from 'nestjs-otel';
import { inboxConfiguration } from '~/db';
import {
  InboxConfigurationMailFilters,
  inboxConfigurationMailFilters,
} from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
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

export type BatchResult =
  | { outcome: 'batch-uploaded' }
  | { outcome: 'completed' }
  | { outcome: 'version-mismatch' };

const BURST_LIMIT = 100;
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
  public async processBatch({
    userProfileId,
    version,
  }: {
    userProfileId: string;
    version: string;
  }): Promise<BatchResult> {
    traceAttrs({ userProfileId, version });

    this.logger.log({ userProfileId, version, msg: 'Starting batch processing' });

    const config = await this.findConfigByVersion.run(userProfileId, version);
    if (!config?.fullSyncNextLink) {
      this.logger.log({ userProfileId, version, msg: 'Version mismatch on config load' });
      return { outcome: 'version-mismatch' };
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

    let nextLink: string | null = fullSyncNextLink;
    let batchIndex = fullSyncBatchIndex;
    let uploaded = 0;
    let skipped = 0;
    let failed = 0;
    let pageNumber = 0;

    while (nextLink) {
      pageNumber++;
      const pageStart = Date.now();
      const pageData = await this.fetchPage(client, nextLink, filters, userProfileId, version);
      const pageDurationMs = Date.now() - pageStart;
      this.graphPageDuration.record(pageDurationMs / 1000, { page_type: nextLink === START_FULL_SYNC_LINK ? 'first' : 'next' });
      const page = pageData.messages;

      this.logger.log({
        userProfileId,
        version,
        pageNumber,
        pageSize: page.length,
        pageDurationMs,
        resumeFromIndex: batchIndex,
        msg: 'Graph API page fetched',
      });

      if (page.length === 0) {
        this.logger.log({ userProfileId, version, pageNumber, msg: 'Empty page, ending' });
        break;
      }

      for (let i = batchIndex; i < page.length; i++) {
        const message = page[i];
        if (!message) {
          continue;
        }

        const result = await this.processMessage({
          message,
          filters,
          userProfileId,
          version,
        });

        if (result === 'version-mismatch') {
          this.logger.log({
            userProfileId,
            version,
            pageNumber,
            messageIndex: i,
            uploaded,
            skipped,
            failed,
            msg: 'Version mismatch during message processing',
          });
          return { outcome: 'version-mismatch' };
        }

        if (result === 'ingested') {
          uploaded++;
        } else if (result === 'skipped') {
          skipped++;
        } else {
          failed++;
        }

        if (uploaded >= BURST_LIMIT) {
          const saved = await this.updateByVersionCommand.run(userProfileId, version, {
            fullSyncBatchIndex: i + 1,
            fullSyncHeartbeatAt: sql`NOW()`,
          });
          if (!saved) {
            return { outcome: 'version-mismatch' };
          }
          traceEvent('batch-uploaded', { uploaded, skipped, failed });
          this.logger.log({
            userProfileId,
            version,
            pageNumber,
            messageIndex: i + 1,
            uploaded,
            skipped,
            failed,
            msg: 'Burst limit reached, parking',
          });
          return { outcome: 'batch-uploaded' };
        }
      }

      batchIndex = 0;
      nextLink = pageData.nextLink;

      const saved = await this.updateByVersionCommand.run(userProfileId, version, {
        fullSyncNextLink: nextLink,
        fullSyncBatchIndex: 0,
        fullSyncHeartbeatAt: sql`NOW()`,
      });
      if (!saved) {
        return { outcome: 'version-mismatch' };
      }

      await this.updateWatermarks(page, userProfileId, version);

      this.logger.log({
        userProfileId,
        version,
        pageNumber,
        hasNextPage: nextLink !== null,
        uploaded,
        skipped,
        failed,
        msg: 'Page processing complete',
      });
    }

    traceEvent('full-sync-completed', { uploaded, skipped, failed, pageNumber });
    this.logger.log({
      userProfileId,
      version,
      uploaded,
      skipped,
      failed,
      totalPages: pageNumber,
      msg: 'All pages processed',
    });
    return { outcome: 'completed' };
  }

  private async fetchPage(
    client: ReturnType<GraphClientFactory['createClientForUser']>,
    nextLink: string,
    filters: InboxConfigurationMailFilters,
    userProfileId: string,
    version: string,
  ): Promise<{ messages: FullSyncBatchGraphMessage[]; nextLink: string | null }> {
    const conditions = [`createdDateTime gt ${filters.ignoredBefore.toISOString()}`];

    let raw: unknown;
    if (nextLink !== START_FULL_SYNC_LINK) {
      try {
        raw = await client.api(nextLink).header('Prefer', 'IdType="ImmutableId"').get();
      } catch (error) {
        const isExpiredNextLink = error instanceof GraphError && error.statusCode === 410;
        if (!isExpiredNextLink) {
          throw error;
        }
        this.logger.warn({ userProfileId, msg: 'Graph API nextLink expired (410), falling back to first page' });
        const freshConfig = await this.findConfigByVersion.run(userProfileId, version);
        if (freshConfig?.oldestCreatedDateTime) {
          conditions.push(`createdDateTime le ${freshConfig.oldestCreatedDateTime.toISOString()}`);
        }
        raw = await this.fetchFirstPage(client, conditions);
      }
    } else {
      raw = await this.fetchFirstPage(client, conditions);
    }

    const parsed = fullSyncBatchGraphMessageResponseSchema.parse(raw);
    return {
      messages: parsed.value,
      nextLink: parsed['@odata.nextLink'] ?? null,
    };
  }

  private async fetchFirstPage(
    client: ReturnType<GraphClientFactory['createClientForUser']>,
    conditions: string[],
  ): Promise<unknown> {
    return client
      .api('me/messages')
      .header('Prefer', 'IdType="ImmutableId"')
      .select(FullSyncBatchGraphMessageFields)
      .filter(conditions.join(' and '))
      .orderby('createdDateTime desc')
      .top(200)
      .get();
  }

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

    const startTime = Date.now();
    const ingested = await this.ingestWithRetries(userProfileId, message.id);
    const durationSeconds = (Date.now() - startTime) / 1000;
    this.ingestionDuration.record(durationSeconds, { outcome: ingested ? 'success' : 'failure' });

    if (ingested) {
      this.messagesProcessed.add(1, { outcome: 'ingested' });
      const saved = await this.updateByVersionCommand.run(userProfileId, version, {
        fullSyncScheduledForIngestion: sql`${inboxConfiguration.fullSyncScheduledForIngestion} + 1`,
        fullSyncHeartbeatAt: sql`NOW()`,
      });
      return saved ? 'ingested' : 'version-mismatch';
    }

    this.messagesProcessed.add(1, { outcome: 'failed' });
    this.logger.warn({ userProfileId, messageId: message.id, msg: 'Message ingestion failed after retries' });
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

  private async updateWatermarks(
    batch: FullSyncBatchGraphMessage[],
    userProfileId: string,
    version: string,
  ): Promise<void> {
    if (batch.length === 0) {
      return;
    }

    const createdDates = batch.map((e) => new Date(e.createdDateTime));
    const batchNewestCreated = new Date(Math.max(...createdDates.map((d) => d.getTime())));
    const batchOldestCreated = new Date(Math.min(...createdDates.map((d) => d.getTime())));

    await this.updateByVersionCommand.run(userProfileId, version, {
      newestCreatedDateTime: sql`GREATEST(COALESCE(${inboxConfiguration.newestCreatedDateTime}, '-infinity'::timestamptz), ${batchNewestCreated})`,
      oldestCreatedDateTime: sql`LEAST(COALESCE(${inboxConfiguration.oldestCreatedDateTime}, 'infinity'::timestamptz), ${batchOldestCreated})`,
    });
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
