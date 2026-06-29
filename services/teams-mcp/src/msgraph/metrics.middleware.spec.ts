import type { Context, Middleware } from '@microsoft/microsoft-graph-client';
import type { MetricService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MetricsMiddleware } from './metrics.middleware';

const mockCounter = { add: vi.fn() };
const mockHistogram = { record: vi.fn() };
const mockMetricService: Pick<MetricService, 'getCounter' | 'getHistogram'> = {
  getCounter: vi.fn().mockReturnValue(mockCounter),
  getHistogram: vi.fn().mockReturnValue(mockHistogram),
};

function makeContext(): Context {
  return {
    request: 'https://graph.microsoft.com/v1.0/chats/abc/messages',
    options: { method: 'GET' },
  } as Context;
}

function throwingNext(error: unknown): Middleware {
  return {
    execute: vi.fn().mockRejectedValue(error),
    setNext: vi.fn(),
  };
}

describe('MetricsMiddleware request counter on failure', () => {
  let unit: MetricsMiddleware;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new MetricsMiddleware(mockMetricService as MetricService);
  });

  it('records status_class "network" when the failure is a transport error', async () => {
    const networkError = new TypeError('fetch failed');
    (networkError as NodeJS.ErrnoException).cause = Object.assign(new Error('EAI_AGAIN'), {
      code: 'EAI_AGAIN',
    });
    unit.setNext(throwingNext(networkError));

    await expect(unit.execute(makeContext())).rejects.toBe(networkError);

    expect(mockCounter.add).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ status_class: 'network' }),
    );
  });

  it('records status_class "5xx" when the failure is not a transport error', async () => {
    const serverError = new Error('Error while processing response.');
    unit.setNext(throwingNext(serverError));

    await expect(unit.execute(makeContext())).rejects.toBe(serverError);

    expect(mockCounter.add).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ status_class: '5xx' }),
    );
  });
});
