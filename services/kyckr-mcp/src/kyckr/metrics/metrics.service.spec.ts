import type { MetricService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Metrics } from './metrics.service';

const mockCounters = {
  kyckr_search_companies_calls_total: { add: vi.fn() },
  kyckr_lite_profile_fetches_total: { add: vi.fn() },
  kyckr_enhanced_profile_fetches_total: { add: vi.fn() },
  kyckr_company_documents_list_calls_total: { add: vi.fn() },
  kyckr_document_orders_total: { add: vi.fn() },
  kyckr_get_order_calls_total: { add: vi.fn() },
  kyckr_list_orders_calls_total: { add: vi.fn() },
  kyckr_credits_consumed_total: { add: vi.fn() },
};

const mockMetricService: Pick<MetricService, 'getCounter'> = {
  getCounter: vi.fn((name: keyof typeof mockCounters) => mockCounters[name]),
};

describe('Metrics', () => {
  let unit: Metrics;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new Metrics(mockMetricService as MetricService);
  });

  it('records tool calls against the matching counter', () => {
    unit.recordToolCall('search_companies', 'success');
    unit.recordToolCall('get_order', 'error');

    expect(mockCounters.kyckr_search_companies_calls_total.add).toHaveBeenCalledWith(1, {
      result: 'success',
    });
    expect(mockCounters.kyckr_get_order_calls_total.add).toHaveBeenCalledWith(1, {
      result: 'error',
    });
  });

  it('records positive credit consumption with the tool label', () => {
    unit.recordCreditsConsumed('get_lite_profile', { value: 3 });

    expect(mockCounters.kyckr_credits_consumed_total.add).toHaveBeenCalledWith(3, {
      tool: 'get_lite_profile',
    });
  });

  it('skips empty credit values', () => {
    unit.recordCreditsConsumed('get_lite_profile', undefined);
    unit.recordCreditsConsumed('get_lite_profile', { value: 0 });

    expect(mockCounters.kyckr_credits_consumed_total.add).not.toHaveBeenCalled();
  });
});
