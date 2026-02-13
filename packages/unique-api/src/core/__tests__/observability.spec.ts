import type { Meter } from '@opentelemetry/api';
import { describe, expect, it, vi } from 'vitest';

import { createUniqueApiMetrics } from '../observability';

function createMockMeter() {
  return {
    createCounter: vi.fn().mockReturnValue({ add: vi.fn() }),
    createHistogram: vi.fn().mockReturnValue({ record: vi.fn() }),
  } as unknown as Meter & {
    createCounter: ReturnType<typeof vi.fn>;
    createHistogram: ReturnType<typeof vi.fn>;
  };
}

describe('createUniqueApiMetrics', () => {
  it('creates all metric instruments with correct names', () => {
    const mockMeter = createMockMeter();

    const metrics = createUniqueApiMetrics(mockMeter, 'unique_api');

    expect(metrics.requestsTotal).toBeDefined();
    expect(metrics.errorsTotal).toBeDefined();
    expect(metrics.requestDurationMs).toBeDefined();
    expect(metrics.slowRequestsTotal).toBeDefined();
    expect(metrics.authTokenRefreshTotal).toBeDefined();

    expect(mockMeter.createCounter).toHaveBeenCalledWith(
      'unique_api_requests_total',
      expect.any(Object),
    );
    expect(mockMeter.createCounter).toHaveBeenCalledWith(
      'unique_api_errors_total',
      expect.any(Object),
    );
    expect(mockMeter.createHistogram).toHaveBeenCalledWith(
      'unique_api_request_duration_ms',
      expect.any(Object),
    );
    expect(mockMeter.createCounter).toHaveBeenCalledWith(
      'unique_api_slow_requests_total',
      expect.any(Object),
    );
    expect(mockMeter.createCounter).toHaveBeenCalledWith(
      'unique_api_auth_token_refresh_total',
      expect.any(Object),
    );
  });

  it('uses provided prefix for all metric names', () => {
    const mockMeter = createMockMeter();

    createUniqueApiMetrics(mockMeter, 'spc_unique');

    expect(mockMeter.createCounter).toHaveBeenCalledWith(
      'spc_unique_requests_total',
      expect.any(Object),
    );
    expect(mockMeter.createCounter).toHaveBeenCalledWith(
      'spc_unique_errors_total',
      expect.any(Object),
    );
    expect(mockMeter.createHistogram).toHaveBeenCalledWith(
      'spc_unique_request_duration_ms',
      expect.any(Object),
    );
    expect(mockMeter.createCounter).toHaveBeenCalledWith(
      'spc_unique_slow_requests_total',
      expect.any(Object),
    );
    expect(mockMeter.createCounter).toHaveBeenCalledWith(
      'spc_unique_auth_token_refresh_total',
      expect.any(Object),
    );
  });

  it('instruments have correct descriptions', () => {
    const mockMeter = createMockMeter();

    createUniqueApiMetrics(mockMeter, 'unique_api');

    expect(mockMeter.createCounter).toHaveBeenCalledWith('unique_api_requests_total', {
      description: 'Total number of Unique API requests',
    });
    expect(mockMeter.createCounter).toHaveBeenCalledWith('unique_api_errors_total', {
      description: 'Total number of Unique API errors',
    });
    expect(mockMeter.createHistogram).toHaveBeenCalledWith('unique_api_request_duration_ms', {
      description: 'Duration of Unique API requests in milliseconds',
      unit: 'ms',
    });
    expect(mockMeter.createCounter).toHaveBeenCalledWith('unique_api_slow_requests_total', {
      description: 'Total number of slow Unique API requests by duration bucket',
    });
    expect(mockMeter.createCounter).toHaveBeenCalledWith('unique_api_auth_token_refresh_total', {
      description: 'Total number of auth token refreshes',
    });
  });
});
