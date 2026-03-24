import { Injectable } from '@nestjs/common';
import type { Counter, Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';

@Injectable()
export class ConfConMetrics {
  public readonly syncDuration: Histogram;
  public readonly scanDuration: Histogram;
  public readonly pagesProcessed: Counter;
  public readonly attachmentsProcessed: Counter;
  public readonly contentDeleted: Counter;
  public readonly fileDiffEvents: Counter;
  public readonly attachmentUploadDuration: Histogram;
  public readonly confluenceApiRequestDuration: Histogram;
  public readonly confluenceApiThrottleEvents: Counter;
  public readonly confluenceApiErrors: Counter;

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
          explicitBucketBoundaries: [0.1, 0.5, 1, 2, 5, 10, 20],
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

  /**
   * Initializes all counters for a tenant by recording a zero value. This ensures Prometheus
   * scrapes a baseline before the first sync, so that `increase()` can compute a correct
   * delta from 0 → N on the first sync cycle after startup.
   */
  public initializeCountersForTenant(tenantName: string): void {
    const tenant = { tenant: tenantName };
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
    this.confluenceApiErrors.add(0, { ...tenant, http_status_class: '2xx' });
  }
}
