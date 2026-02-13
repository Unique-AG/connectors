import { describe, expect, it, vi } from 'vitest';
import type { UniqueApiClient, UniqueApiClientConfig, UniqueApiClientFactory } from '../types';
import { UniqueApiClientRegistryImpl } from '../unique-api-client.registry';

function createMockClient(overrides?: Partial<UniqueApiClient>): UniqueApiClient {
  return {
    auth: { getToken: vi.fn() },
    scopes: {} as UniqueApiClient['scopes'],
    files: {} as UniqueApiClient['files'],
    users: {} as UniqueApiClient['users'],
    groups: {} as UniqueApiClient['groups'],
    ingestion: {} as UniqueApiClient['ingestion'],
    close: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function createMockFactory(client: UniqueApiClient): UniqueApiClientFactory {
  return { create: vi.fn().mockReturnValue(client) };
}

const dummyConfig = {} as UniqueApiClientConfig;

describe('UniqueApiClientRegistryImpl', () => {
  describe('get', () => {
    it('returns undefined for unknown key', () => {
      const factory = createMockFactory(createMockClient());
      const registry = new UniqueApiClientRegistryImpl(factory);

      expect(registry.get('unknown')).toBeUndefined();
    });
  });

  describe('getOrCreate', () => {
    it('creates client via factory and returns it', async () => {
      const client = createMockClient();
      const factory = createMockFactory(client);
      const registry = new UniqueApiClientRegistryImpl(factory);

      const result = await registry.getOrCreate('key-1', dummyConfig);

      expect(result).toBe(client);
      expect(factory.create).toHaveBeenCalledWith(dummyConfig);
    });

    it('returns existing client on second call without duplicate creation', async () => {
      const client = createMockClient();
      const factory = createMockFactory(client);
      const registry = new UniqueApiClientRegistryImpl(factory);

      const first = await registry.getOrCreate('key-1', dummyConfig);
      const second = await registry.getOrCreate('key-1', dummyConfig);

      expect(first).toBe(second);
      expect(factory.create).toHaveBeenCalledOnce();
    });
  });

  describe('set', () => {
    it('stores client and makes it retrievable via get', () => {
      const client = createMockClient();
      const factory = createMockFactory(createMockClient());
      const registry = new UniqueApiClientRegistryImpl(factory);

      registry.set('key-1', client);

      expect(registry.get('key-1')).toBe(client);
    });

    it('throws on duplicate key', () => {
      const factory = createMockFactory(createMockClient());
      const registry = new UniqueApiClientRegistryImpl(factory);

      registry.set('key-1', createMockClient());

      expect(() => registry.set('key-1', createMockClient())).toThrow(
        'UniqueApiClient with key "key-1" is already registered',
      );
    });
  });

  describe('delete', () => {
    it('removes client and calls close()', async () => {
      const client = createMockClient();
      const factory = createMockFactory(client);
      const registry = new UniqueApiClientRegistryImpl(factory);

      await registry.getOrCreate('key-1', dummyConfig);
      await registry.delete('key-1');

      expect(client.close).toHaveBeenCalledOnce();
      expect(registry.get('key-1')).toBeUndefined();
    });

    it('no-ops for unknown key', async () => {
      const factory = createMockFactory(createMockClient());
      const registry = new UniqueApiClientRegistryImpl(factory);

      await expect(registry.delete('missing')).resolves.toBeUndefined();
    });
  });

  describe('clear', () => {
    it('closes all clients and empties the registry', async () => {
      const client1 = createMockClient();
      const client2 = createMockClient();
      const factory = { create: vi.fn() } as unknown as UniqueApiClientFactory;

      (factory.create as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(client1)
        .mockReturnValueOnce(client2);

      const registry = new UniqueApiClientRegistryImpl(factory);

      await registry.getOrCreate('a', dummyConfig);
      await registry.getOrCreate('b', dummyConfig);
      await registry.clear();

      expect(client1.close).toHaveBeenCalledOnce();
      expect(client2.close).toHaveBeenCalledOnce();
      expect(registry.get('a')).toBeUndefined();
      expect(registry.get('b')).toBeUndefined();
    });

    it('resolves even when close() rejects', async () => {
      const failingClient = createMockClient({
        close: vi.fn().mockRejectedValue(new Error('close failed')),
      });
      const factory = createMockFactory(failingClient);
      const registry = new UniqueApiClientRegistryImpl(factory);

      await registry.getOrCreate('key-1', dummyConfig);

      await expect(registry.clear()).resolves.toBeUndefined();
      expect(registry.get('key-1')).toBeUndefined();
    });

    it('handles clients without close()', async () => {
      const clientWithoutClose = createMockClient({ close: undefined });
      const factory = createMockFactory(clientWithoutClose);
      const registry = new UniqueApiClientRegistryImpl(factory);

      await registry.getOrCreate('key-1', dummyConfig);

      await expect(registry.clear()).resolves.toBeUndefined();
      expect(registry.get('key-1')).toBeUndefined();
    });
  });
});
