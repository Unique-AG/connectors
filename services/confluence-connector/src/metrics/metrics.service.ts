import { getHttpStatusCodeClass } from '@unique-ag/utils';
import { Injectable } from '@nestjs/common';
import type { Counter, Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import { getCurrentTenant } from '../tenant';

@Injectable()
export class Metrics {
  private readonly syncDuration: Histogram;
  private readonly scanDuration: Histogram;
  private readonly pagesProcessed: Counter;
  private readonly attachmentsProcessed: Counter;
  private readonly contentDeleted: Counter;
  private readonly fileDiffEvents: Counter;
  private readonly attachmentUploadDuration: Histogram;
  private readonly confluenceApiRequestDuration: Histogram;
  private readonly confluenceApiThrottleEvents: Counter;
  private readonly confluenceApiErrors: Counter;

  public constructor(metricService: MetricService) {
    this.syncDuration = metricService.getHistogram('cfc_sync_duration_seconds', {
      description: 'Duration of Confluence synchronization cycles',
    });

    this.scanDuration = metricService.getHistogram('cfc_scan_duration_seconds', {
      description: 'Duration of the Confluence page discovery (scan) phase',
    });

    this.attachmentUploadDuration = metricService.getHistogram(
      'cfc_attachment_upload_duration_seconds',
      {
        description: 'Duration of a single attachment upload to Unique',
        advice: {
          explicitBucketBoundaries: [0.1, 0.2, 0.5, 1, 2, 3, 5, 10, 20, 30, 60],
        },
      },
    );

    this.pagesProcessed = metricService.getCounter('cfc_pages_processed_total', {
      description: 'Number of pages processed during ingestion',
    });

    this.attachmentsProcessed = metricService.getCounter('cfc_attachments_processed_total', {
      description: 'Number of attachments processed during ingestion',
    });

    this.contentDeleted = metricService.getCounter('cfc_content_deleted_total', {
      description: 'Number of content items deleted from Unique',
    });

    this.fileDiffEvents = metricService.getCounter('cfc_file_diff_events_total', {
      description: 'Number of file change detection events (new, updated, deleted, moved)',
    });

    this.confluenceApiRequestDuration = metricService.getHistogram(
      'cfc_confluence_api_request_duration_seconds',
      {
        description: 'Request latency for Confluence API calls',
        advice: {
          explicitBucketBoundaries: [0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
        },
      },
    );

    this.confluenceApiThrottleEvents = metricService.getCounter(
      'cfc_confluence_api_throttle_events_total',
      {
        description: 'Number of Confluence API rate-limit throttling events',
      },
    );

    this.confluenceApiErrors = metricService.getCounter('cfc_confluence_api_errors_total', {
      description: 'Number of Confluence API error responses',
    });
  }

  private get tenantName(): string {
    return getCurrentTenant().name;
  }

  public recordSyncDuration(durationSeconds: number, result: 'success' | 'failure'): void {
    this.syncDuration.record(durationSeconds, {
      tenant: this.tenantName,
      result,
    });
  }

  public recordScanDuration(durationSeconds: number): void {
    this.scanDuration.record(durationSeconds, { tenant: this.tenantName });
  }

  public recordPagesProcessed(count: number, result: 'success' | 'failure'): void {
    this.pagesProcessed.add(count, { tenant: this.tenantName, result });
  }

  public recordAttachmentsProcessed(count: number, result: 'success' | 'failure'): void {
    this.attachmentsProcessed.add(count, { tenant: this.tenantName, result });
  }

  public recordContentDeleted(count: number, result: 'success' | 'failure'): void {
    this.contentDeleted.add(count, { tenant: this.tenantName, result });
  }

  public recordFileDiffEvents(
    count: number,
    diffResultType: 'new' | 'updated' | 'deleted' | 'moved',
  ): void {
    this.fileDiffEvents.add(count, {
      tenant: this.tenantName,
      diff_result_type: diffResultType,
    });
  }

  public recordAttachmentUploadDuration(durationSeconds: number): void {
    this.attachmentUploadDuration.record(durationSeconds, {
      tenant: this.tenantName,
    });
  }

  public recordApiRequestDuration(
    durationSeconds: number,
    endpoint: string,
    result: 'success' | 'error',
  ): void {
    this.confluenceApiRequestDuration.record(durationSeconds, {
      tenant: this.tenantName,
      endpoint,
      result,
    });
  }

  public recordApiError(statusCode?: number): void {
    this.confluenceApiErrors.add(1, {
      tenant: this.tenantName,
      http_status_class: statusCode ? getHttpStatusCodeClass(statusCode) : 'unknown',
    });
  }

  public recordApiThrottleEvent(): void {
    // Bottleneck's reservoir-refresh timer can fire `depleted` outside any AsyncLocalStorage
    // context, so the tenantName getter (which asserts) may throw here.
    // Adding this to meet bugbot's criteria, as in practice I was never able to reproduce that issue.
    let tenant: string;
    try {
      tenant = this.tenantName;
    } catch {
      tenant = 'unknown';
    }
    this.confluenceApiThrottleEvents.add(1, { tenant });
  }

  /**
   * Initializes all counters for the current tenant by recording a zero value. This ensures
   * Prometheus scrapes a baseline before the first sync, so that `increase()` can compute a
   * correct delta from 0 -> N on the first sync cycle after startup.
   */
  public initializeCounters(): void {
    const tenant = { tenant: this.tenantName };
    this.pagesProcessed.add(0, { ...tenant, result: 'success' });
    this.pagesProcessed.add(0, { ...tenant, result: 'failure' });
    this.attachmentsProcessed.add(0, { ...tenant, result: 'success' });
    this.attachmentsProcessed.add(0, { ...tenant, result: 'failure' });
    this.contentDeleted.add(0, { ...tenant, result: 'success' });
    this.contentDeleted.add(0, { ...tenant, result: 'failure' });
    this.fileDiffEvents.add(0, { ...tenant, diff_result_type: 'new' });
    this.fileDiffEvents.add(0, { ...tenant, diff_result_type: 'updated' });
    this.fileDiffEvents.add(0, { ...tenant, diff_result_type: 'deleted' });
    this.fileDiffEvents.add(0, { ...tenant, diff_result_type: 'moved' });
    this.confluenceApiThrottleEvents.add(0, tenant);
  }
}
