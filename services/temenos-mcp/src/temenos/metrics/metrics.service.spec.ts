import type { MetricService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Metrics } from './metrics.service';

const mockMetrics = {
  temenos_tool_call_duration_ms: { record: vi.fn() },
  temenos_api_requests_total: { add: vi.fn() },
  temenos_api_request_duration_ms: { record: vi.fn() },
};

type CounterName = 'temenos_api_requests_total';
type HistogramName = 'temenos_tool_call_duration_ms' | 'temenos_api_request_duration_ms';

const mockMetricService: Pick<MetricService, 'getCounter' | 'getHistogram'> = {
  getCounter: vi.fn((name: CounterName) => mockMetrics[name]),
  getHistogram: vi.fn((name: HistogramName) => mockMetrics[name]),
};

describe('Metrics', () => {
  let unit: Metrics;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new Metrics(mockMetricService as MetricService);
  });

  it('records tool call duration in milliseconds with tool and result labels', () => {
    vi.useFakeTimers();
    try {
      const firstStart = Date.now();
      vi.advanceTimersByTime(1500);
      unit.recordToolDuration('get_countries', 'success', firstStart);

      const secondStart = Date.now();
      vi.advanceTimersByTime(250);
      unit.recordToolDuration('get_guarantees', 'error', secondStart);

      expect(mockMetrics.temenos_tool_call_duration_ms.record).toHaveBeenNthCalledWith(1, 1500, {
        tool: 'get_countries',
        result: 'success',
      });
      expect(mockMetrics.temenos_tool_call_duration_ms.record).toHaveBeenNthCalledWith(2, 250, {
        tool: 'get_guarantees',
        result: 'error',
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('records api requests against a counter labelled by path and stringified status', () => {
    unit.recordApiRequest({ path: '/reference/v1.0.0/countries', status: 200, durationMs: 123 });
    unit.recordApiRequest({ path: '/order/v1.0.0/payments', status: 500, durationMs: 45 });

    expect(mockMetrics.temenos_api_requests_total.add).toHaveBeenNthCalledWith(1, 1, {
      path: '/reference/v1.0.0/countries',
      status: '200',
    });
    expect(mockMetrics.temenos_api_requests_total.add).toHaveBeenNthCalledWith(2, 1, {
      path: '/order/v1.0.0/payments',
      status: '500',
    });
  });

  it('records api request duration in milliseconds with the path label', () => {
    unit.recordApiRequest({ path: '/reference/v1.0.0/countries', status: 200, durationMs: 87 });

    expect(mockMetrics.temenos_api_request_duration_ms.record).toHaveBeenCalledWith(87, {
      path: '/reference/v1.0.0/countries',
    });
  });

  it('records transport-error api calls with status 0', () => {
    unit.recordApiRequest({ path: '/reference/v1.0.0/lookups', status: 0, durationMs: 12 });

    expect(mockMetrics.temenos_api_requests_total.add).toHaveBeenCalledWith(1, {
      path: '/reference/v1.0.0/lookups',
      status: '0',
    });
    expect(mockMetrics.temenos_api_request_duration_ms.record).toHaveBeenCalledWith(12, {
      path: '/reference/v1.0.0/lookups',
    });
  });
});
