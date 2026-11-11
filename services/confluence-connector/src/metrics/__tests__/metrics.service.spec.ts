import { createMock, type DeepMocked } from '@golevelup/ts-vitest';
import type { Counter, Histogram, ObservableGauge } from '@opentelemetry/api';
import type { MetricService } from 'nestjs-otel';
import { afterEach, describe, expect, it, type Mock, vi } from 'vitest';
import { createMockTenant } from '../../synchronization/__mocks__/sync.fixtures';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import { Metrics, SyncPhase } from '../metrics.service';

function getOrThrow<V>(map: Map<string, V>, key: string): V {
  const val = map.get(key);
  if (!val) {
    throw new Error(`Expected map entry for key "${key}" to exist`);
  }
  return val;
}

function makeMetricService(): {
  metricService: MetricService;
  histograms: Map<string, DeepMocked<Histogram>>;
  counters: Map<string, DeepMocked<Counter>>;
  gauges: Map<string, DeepMocked<ObservableGauge>>;
} {
  const histograms = new Map<string, DeepMocked<Histogram>>();
  const counters = new Map<string, DeepMocked<Counter>>();
  const gauges = new Map<string, DeepMocked<ObservableGauge>>();

  const metricService = createMock<MetricService>({
    getHistogram: vi.fn((name: string) => {
      const h = createMock<Histogram>();
      histograms.set(name, h);
      return h;
    }),
    getCounter: vi.fn((name: string) => {
      const c = createMock<Counter>();
      counters.set(name, c);
      return c;
    }),
    getObservableGauge: vi.fn((name: string) => {
      const g = createMock<ObservableGauge>();
      gauges.set(name, g);
      return g;
    }),
  });

  return { metricService, histograms, counters, gauges };
}

const tenant = createMockTenant('test-tenant');

describe('Metrics', () => {
  describe('recordSyncResult', () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it('records duration and counts the sync with tenant and result labels', () => {
      const { metricService, histograms, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordSyncResult(0.3, 'failure');
      });

      const labels = { tenant: 'test-tenant', result: 'failure' };
      expect(histograms.get('cfc_sync_duration_seconds')?.record).toHaveBeenCalledWith(0.3, labels);
      expect(counters.get('cfc_syncs_total')?.add).toHaveBeenCalledWith(1, labels);
    });

    it('reports the time of the last successful sync', () => {
      vi.useFakeTimers({ now: new Date('2026-11-11T10:00:00Z') });
      const { metricService, gauges } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordSyncResult(1.5, 'success');
      });
      vi.setSystemTime(new Date('2026-11-11T11:00:00Z'));
      tenantStorage.run(tenant, () => {
        metrics.recordSyncResult(1.5, 'failure');
      });

      const gauge = getOrThrow(gauges, 'cfc_last_successful_sync_timestamp_seconds');
      // biome-ignore lint/style/noNonNullAssertion: The gauge registers its callback in the constructor
      const callback = gauge.addCallback.mock.calls[0]![0] as (obs: { observe: Mock }) => void;
      const observe = vi.fn();
      callback({ observe });

      expect(observe).toHaveBeenCalledExactlyOnceWith(Date.parse('2026-11-11T10:00:00Z') / 1000, {
        tenant: 'test-tenant',
      });
    });

    it('reports no last successful sync before the first success', () => {
      const { metricService, gauges } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordSyncResult(0.3, 'failure');
      });

      const gauge = getOrThrow(gauges, 'cfc_last_successful_sync_timestamp_seconds');
      // biome-ignore lint/style/noNonNullAssertion: The gauge registers its callback in the constructor
      const callback = gauge.addCallback.mock.calls[0]![0] as (obs: { observe: Mock }) => void;
      const observe = vi.fn();
      callback({ observe });

      expect(observe).not.toHaveBeenCalled();
    });
  });

  describe('recordCleanupResult', () => {
    it('records duration and counts the cleanup run with tenant and result labels', () => {
      const { metricService, histograms, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordCleanupResult(4, 'success');
      });

      const labels = { tenant: 'test-tenant', result: 'success' };
      expect(histograms.get('cfc_cleanup_duration_seconds')?.record).toHaveBeenCalledWith(
        4,
        labels,
      );
      expect(counters.get('cfc_tenant_cleanups_total')?.add).toHaveBeenCalledWith(1, labels);
    });
  });

  describe('recordScanDuration', () => {
    it('records duration with tenant label', () => {
      const { metricService, histograms } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordScanDuration(2.0);
      });

      expect(histograms.get('cfc_scan_duration_seconds')?.record).toHaveBeenCalledWith(2.0, {
        tenant: 'test-tenant',
      });
    });
  });

  describe('recordPagesProcessed', () => {
    it('adds count with tenant and result labels', () => {
      const { metricService, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordPagesProcessed(5, 'success');
      });

      expect(counters.get('cfc_pages_processed_total')?.add).toHaveBeenCalledWith(5, {
        tenant: 'test-tenant',
        result: 'success',
      });
    });

    it('supports skipped result label', () => {
      const { metricService, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordPagesProcessed(2, 'skipped');
      });

      expect(counters.get('cfc_pages_processed_total')?.add).toHaveBeenCalledWith(2, {
        tenant: 'test-tenant',
        result: 'skipped',
      });
    });
  });

  describe('recordAttachmentsProcessed', () => {
    it('adds count with tenant and result labels', () => {
      const { metricService, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordAttachmentsProcessed(3, 'failure');
      });

      expect(counters.get('cfc_attachments_processed_total')?.add).toHaveBeenCalledWith(3, {
        tenant: 'test-tenant',
        result: 'failure',
      });
    });
  });

  describe('recordFileDiffEvents', () => {
    it.each(['new', 'updated', 'deleted', 'moved'] as const)(
      'adds count with diff_result_type=%s',
      (diffResultType) => {
        const { metricService, counters } = makeMetricService();
        const metrics = new Metrics(metricService);

        tenantStorage.run(tenant, () => {
          metrics.recordFileDiffEvents(1, diffResultType);
        });

        expect(counters.get('cfc_file_diff_events_total')?.add).toHaveBeenCalledWith(1, {
          tenant: 'test-tenant',
          diff_result_type: diffResultType,
        });
      },
    );
  });

  describe('recordApiError', () => {
    it('records with http_status_class label for known status codes', () => {
      const { metricService, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordApiError(404);
      });

      expect(counters.get('cfc_confluence_api_errors_total')?.add).toHaveBeenCalledWith(1, {
        tenant: 'test-tenant',
        http_status_class: expect.stringContaining('4'),
      });
    });

    it('records with http_status_class=unknown when no status code provided', () => {
      const { metricService, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordApiError();
      });

      expect(counters.get('cfc_confluence_api_errors_total')?.add).toHaveBeenCalledWith(1, {
        tenant: 'test-tenant',
        http_status_class: 'unknown',
      });
    });
  });

  describe('recordApiThrottleEvent', () => {
    it('records with tenant label when inside tenant context', () => {
      const { metricService, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordApiThrottleEvent();
      });

      expect(counters.get('cfc_confluence_api_throttle_events_total')?.add).toHaveBeenCalledWith(
        1,
        { tenant: 'test-tenant' },
      );
    });

    it('falls back to "unknown" tenant when called outside of tenant context', () => {
      const { metricService, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      metrics.recordApiThrottleEvent();

      expect(counters.get('cfc_confluence_api_throttle_events_total')?.add).toHaveBeenCalledWith(
        1,
        { tenant: 'unknown' },
      );
    });
  });

  describe('setSyncPhase / observable gauge', () => {
    it('cfc_sync_phase gauge observes 1 for the active phase and 0 for all others', () => {
      const { metricService, gauges } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.setSyncPhase(SyncPhase.Scanning);
      });

      const phaseGauge = getOrThrow(gauges, 'cfc_sync_phase');
      expect(phaseGauge.addCallback).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const callback = phaseGauge.addCallback.mock.calls[0]![0] as (obs: { observe: Mock }) => void;

      const observe = vi.fn();
      callback({ observe });

      expect(observe).toHaveBeenCalledWith(1, {
        tenant: 'test-tenant',
        phase: SyncPhase.Scanning,
      });
      expect(observe).toHaveBeenCalledWith(0, { tenant: 'test-tenant', phase: SyncPhase.Idle });
    });
  });

  describe('recordSyncItemTotals / observable gauges', () => {
    it('cfc_sync_pages_total gauge observes stored page count', () => {
      const { metricService, gauges } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordSyncItemTotals(42, 7);
      });

      const pagesGauge = getOrThrow(gauges, 'cfc_sync_pages_total');
      expect(pagesGauge.addCallback).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const callback = pagesGauge.addCallback.mock.calls[0]![0] as (obs: { observe: Mock }) => void;

      const observe = vi.fn();
      callback({ observe });

      expect(observe).toHaveBeenCalledWith(42, { tenant: 'test-tenant' });
    });

    it('cfc_sync_attachments_total gauge observes stored attachment count', () => {
      const { metricService, gauges } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.recordSyncItemTotals(42, 7);
      });

      const attGauge = getOrThrow(gauges, 'cfc_sync_attachments_total');
      expect(attGauge.addCallback).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const callback = attGauge.addCallback.mock.calls[0]![0] as (obs: { observe: Mock }) => void;

      const observe = vi.fn();
      callback({ observe });

      expect(observe).toHaveBeenCalledWith(7, { tenant: 'test-tenant' });
    });
  });

  describe('initializeCounters', () => {
    it('seeds all counters with zero values', () => {
      const { metricService, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.initializeCounters();
      });

      const syncs = getOrThrow(counters, 'cfc_syncs_total');
      expect(syncs.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'success' });
      expect(syncs.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'failure' });

      const pages = getOrThrow(counters, 'cfc_pages_processed_total');
      expect(pages.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'success' });
      expect(pages.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'failure' });
      expect(pages.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'skipped' });

      const fileDiff = getOrThrow(counters, 'cfc_file_diff_events_total');
      expect(fileDiff.add).toHaveBeenCalledWith(0, {
        tenant: 'test-tenant',
        diff_result_type: 'new',
      });
      expect(fileDiff.add).toHaveBeenCalledWith(0, {
        tenant: 'test-tenant',
        diff_result_type: 'deleted',
      });
    });

    it('sets sync phase to Idle in the observable state', () => {
      const { metricService, gauges } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.initializeCounters();
      });

      const phaseGauge = getOrThrow(gauges, 'cfc_sync_phase');
      expect(phaseGauge.addCallback).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const callback = phaseGauge.addCallback.mock.calls[0]![0] as (obs: { observe: Mock }) => void;

      const observe = vi.fn();
      callback({ observe });

      expect(observe).toHaveBeenCalledWith(1, { tenant: 'test-tenant', phase: SyncPhase.Idle });
    });
  });

  describe('initializeCleanupCounters', () => {
    it('seeds cleanup counters with zero values for both result labels', () => {
      const { metricService, counters } = makeMetricService();
      const metrics = new Metrics(metricService);

      tenantStorage.run(tenant, () => {
        metrics.initializeCleanupCounters();
      });

      const runs = getOrThrow(counters, 'cfc_tenant_cleanups_total');
      expect(runs.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'success' });
      expect(runs.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'failure' });

      const content = getOrThrow(counters, 'cfc_cleanup_content_deleted_total');
      expect(content.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'success' });
      expect(content.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'failure' });

      const scopes = getOrThrow(counters, 'cfc_cleanup_scopes_deleted_total');
      expect(scopes.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'success' });
      expect(scopes.add).toHaveBeenCalledWith(0, { tenant: 'test-tenant', result: 'failure' });
    });
  });
});
