import { Cache } from 'cache-manager';
import { vi } from 'vitest';

export class MockCacheManager implements Partial<Cache> {
  // biome-ignore lint/suspicious/noExplicitAny: Mock store for testing
  private store = new Map<string, any>();

  public get = vi.fn().mockImplementation(async (key: string) => {
    return this.store.get(key);
  });

  // biome-ignore lint/suspicious/noExplicitAny: Mock store for testing
  public set = vi.fn().mockImplementation(async (key: string, value: any, _ttl?: number) => {
    this.store.set(key, value);
  });

  public del = vi.fn().mockImplementation(async (key: string) => {
    this.store.delete(key);
  });

  public reset = vi.fn().mockImplementation(async () => {
    this.store.clear();
  });

  public clear = vi.fn().mockImplementation(() => {
    this.store.clear();
  });
}

export const createMockCacheManager = (): MockCacheManager => new MockCacheManager();
