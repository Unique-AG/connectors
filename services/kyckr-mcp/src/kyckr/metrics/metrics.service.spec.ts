import type { MetricService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Metrics } from './metrics.service';

type MetricRegistrar = Pick<MetricService, 'getCounter' | 'getHistogram'>;

const mockMetrics = {
  kyckr_tool_calls_total: { add: vi.fn() },
  kyckr_tool_call_duration_ms: { record: vi.fn() },
  kyckr_credits_consumed_total: { add: vi.fn() },
  kyckr_api_requests_total: { add: vi.fn() },
  kyckr_api_request_duration_ms: { record: vi.fn() },
};

type CounterName =
  | 'kyckr_tool_calls_total'
  | 'kyckr_credits_consumed_total'
  | 'kyckr_api_requests_total';
type HistogramName = 'kyckr_tool_call_duration_ms' | 'kyckr_api_request_duration_ms';

const mockMetricService: MetricRegistrar = {
  getCounter: vi.fn((name: CounterName) => mockMetrics[name]),
  getHistogram: vi.fn((name: HistogramName) => mockMetrics[name]),
};

describe('Metrics', () => {
  let unit: Metrics;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new Metrics(mockMetricService);
  });

  it('records tool calls against a single counter labelled by tool and result', () => {
    unit.recordToolCall('search_companies', 'success');
    unit.recordToolCall('get_order', 'error');

    expect(mockMetrics.kyckr_tool_calls_total.add).toHaveBeenNthCalledWith(1, 1, {
      tool: 'search_companies',
      result: 'success',
    });
    expect(mockMetrics.kyckr_tool_calls_total.add).toHaveBeenNthCalledWith(2, 1, {
      tool: 'get_order',
      result: 'error',
    });
  });

  it('records tool call duration in milliseconds with tool and result labels', () => {
    unit.recordToolDuration('search_companies', 'success', 1500);
    unit.recordToolDuration('get_order', 'error', 250);

    expect(mockMetrics.kyckr_tool_call_duration_ms.record).toHaveBeenNthCalledWith(1, 1500, {
      tool: 'search_companies',
      result: 'success',
    });
    expect(mockMetrics.kyckr_tool_call_duration_ms.record).toHaveBeenNthCalledWith(2, 250, {
      tool: 'get_order',
      result: 'error',
    });
  });

  it('records positive credit consumption with the tool label', () => {
    unit.recordCreditsConsumed('get_lite_profile', { value: 3 });

    expect(mockMetrics.kyckr_credits_consumed_total.add).toHaveBeenCalledWith(3, {
      tool: 'get_lite_profile',
    });
  });

  it('skips empty credit values', () => {
    unit.recordCreditsConsumed('get_lite_profile', undefined);
    unit.recordCreditsConsumed('get_lite_profile', { value: 0 });

    expect(mockMetrics.kyckr_credits_consumed_total.add).not.toHaveBeenCalled();
  });

  it('records api requests against a counter labelled by method, path, and stringified status', () => {
    unit.recordApiRequest({
      method: 'GET',
      path: '/companies/:kyckrId/lite',
      status: 200,
      durationMs: 123,
    });
    unit.recordApiRequest({ method: 'POST', path: '/orders', status: 500, durationMs: 45 });

    expect(mockMetrics.kyckr_api_requests_total.add).toHaveBeenNthCalledWith(1, 1, {
      method: 'GET',
      path: '/companies/:kyckrId/lite',
      status: '200',
    });
    expect(mockMetrics.kyckr_api_requests_total.add).toHaveBeenNthCalledWith(2, 1, {
      method: 'POST',
      path: '/orders',
      status: '500',
    });
  });

  it('records api request duration in milliseconds with method and path labels', () => {
    unit.recordApiRequest({ method: 'GET', path: '/companies', status: 200, durationMs: 87 });

    expect(mockMetrics.kyckr_api_request_duration_ms.record).toHaveBeenCalledWith(87, {
      method: 'GET',
      path: '/companies',
    });
  });

  it('records transport-error api calls with status 0 and the unknown-path sentinel', () => {
    unit.recordApiRequest({ method: 'GET', path: '[unknown]', status: 0, durationMs: 12 });

    expect(mockMetrics.kyckr_api_requests_total.add).toHaveBeenCalledWith(1, {
      method: 'GET',
      path: '[unknown]',
      status: '0',
    });
    expect(mockMetrics.kyckr_api_request_duration_ms.record).toHaveBeenCalledWith(12, {
      method: 'GET',
      path: '[unknown]',
    });
  });
});
