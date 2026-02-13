import * as assert from 'node:assert';
import type {
  UniqueApiClient,
  UniqueApiClientConfig,
  UniqueApiClientFactory,
  UniqueApiClientRegistry,
} from './types';

export class UniqueApiClientRegistryImpl implements UniqueApiClientRegistry {
  private readonly clients = new Map<string, UniqueApiClient>();
  private readonly factory: UniqueApiClientFactory;

  public constructor(factory: UniqueApiClientFactory) {
    this.factory = factory;
  }

  public get(key: string): UniqueApiClient | undefined {
    return this.clients.get(key);
  }

  public async getOrCreate(key: string, config: UniqueApiClientConfig): Promise<UniqueApiClient> {
    const existing = this.clients.get(key);
    if (existing) {
      return existing;
    }

    const client = this.factory.create(config);
    this.clients.set(key, client);
    return client;
  }

  public set(key: string, client: UniqueApiClient): void {
    assert.ok(!this.clients.has(key), `UniqueApiClient with key "${key}" is already registered`);
    this.clients.set(key, client);
  }

  public async delete(key: string): Promise<void> {
    const client = this.clients.get(key);
    if (client) {
      this.clients.delete(key);
      await client.close?.();
    }
  }

  public async clear(): Promise<void> {
    const closePromises: Promise<void>[] = [];
    for (const client of this.clients.values()) {
      if (client.close) {
        closePromises.push(client.close());
      }
    }
    this.clients.clear();
    await Promise.allSettled(closePromises);
  }
}
