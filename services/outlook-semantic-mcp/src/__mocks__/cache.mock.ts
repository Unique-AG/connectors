import { type Mock, vi } from 'vitest';

export class MockCacheManager {
  // biome-ignore lint/suspicious/noExplicitAny: Mock store for testing
  private store = new Map<string, any>();

  public get: Mock = vi.fn().mockImplementation(async (key: string) => {
    return this.store.get(key);
  });

  // biome-ignore lint/suspicious/noExplicitAny: Mock store for testing
  public set: Mock = vi.fn().mockImplementation(async (key: string, value: any, _ttl?: number) => {
    this.store.set(key, value);
  });

  public del: Mock = vi.fn().mockImplementation(async (key: string) => {
    this.store.delete(key);
  });

  public reset: Mock = vi.fn().mockImplementation(async () => {
    this.store.clear();
  });

  public clear: Mock = vi.fn().mockImplementation(() => {
    this.store.clear();
  });
}

export const createMockCacheManager = (): MockCacheManager => new MockCacheManager();
