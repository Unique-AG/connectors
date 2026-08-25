import { interceptors } from 'undici';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { uniqueApiFeatureOptionsFactory } from '../unique-api.module';

describe('uniqueApiFeatureOptionsFactory', () => {
  const composedDispatcher = { kind: 'composed' };
  const compose = vi.fn().mockReturnValue(composedDispatcher);
  const baseDispatcher = { compose };
  const proxyService = {
    getDispatcher: vi.fn().mockReturnValue(baseDispatcher),
  };

  const retryInterceptor = Symbol('retry');
  const redirectInterceptor = Symbol('redirect');

  const configService = {
    get: vi.fn((key: string) => {
      if (key === 'unique') {
        return {
          serviceAuthMode: 'external',
          ingestionServiceBaseUrl: 'https://ingestion.example',
          scopeManagementServiceBaseUrl: 'https://scope.example',
        };
      }
      if (key === 'ingestion') {
        return { connectivityTimeoutMs: 3000 };
      }
      return undefined;
    }),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    proxyService.getDispatcher.mockReturnValue(baseDispatcher);
    compose.mockReturnValue(composedDispatcher);
    configService.get.mockImplementation((key: string) => {
      if (key === 'unique') {
        return {
          serviceAuthMode: 'external',
          ingestionServiceBaseUrl: 'https://ingestion.example',
          scopeManagementServiceBaseUrl: 'https://scope.example',
        };
      }
      if (key === 'ingestion') {
        return { connectivityTimeoutMs: 3000 };
      }
      return undefined;
    });
    vi.spyOn(interceptors, 'retry').mockReturnValue(retryInterceptor as never);
    vi.spyOn(interceptors, 'redirect').mockReturnValue(redirectInterceptor as never);
  });

  it('composes retry and redirect onto a for-external-only dispatcher', () => {
    const result = uniqueApiFeatureOptionsFactory(configService as never, proxyService as never);

    expect(proxyService.getDispatcher).toHaveBeenCalledWith({ mode: 'for-external-only' });
    expect(interceptors.retry).toHaveBeenCalled();
    expect(interceptors.redirect).toHaveBeenCalled();
    expect(compose).toHaveBeenCalledWith([retryInterceptor, redirectInterceptor]);
    expect(result.dispatcher).toBe(composedDispatcher);
  });
});
