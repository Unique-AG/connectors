import type { MetricService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Metrics } from './metrics.service';

const mockMetrics = {
  kyckr_tool_calls_total: { add: vi.fn() },
  kyckr_tool_call_duration_ms: { record: vi.fn() },
  kyckr_credits_consumed_total: { add: vi.fn() },
};

const mockMetricService: Pick<MetricService, 'getCounter' | 'getHistogram'> = {
  getCounter: vi.fn((name: 'kyckr_tool_calls_total' | 'kyckr_credits_consumed_total') => {
    return mockMetrics[name];
  }),
  getHistogram: vi.fn(() => mockMetrics.kyckr_tool_call_duration_ms),
};

describe('Metrics', () => {
  let unit: Metrics;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new Metrics(mockMetricService as MetricService);
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
});
