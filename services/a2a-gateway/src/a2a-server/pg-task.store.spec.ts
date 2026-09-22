import { ServerCallContext } from '@a2a-js/sdk/server';
import { describe, expect, it, vi } from 'vitest';
import { loadConfig } from '../config/config.js';
import type { GatewayDatabase } from '../drizzle/drizzle.module.js';
import { PgTaskStore } from './pg-task.store.js';

function collectStrings(value: unknown, seen = new Set<object>()): string[] {
  if (typeof value === 'string') {
    return [value];
  }
  if (typeof value !== 'object' || value === null || seen.has(value)) {
    return [];
  }
  seen.add(value);
  return Object.values(value).flatMap((item) => collectStrings(item, seen));
}

function context(companyId: string, userId: string): ServerCallContext {
  return new ServerCallContext({
    tenant: companyId,
    user: { isAuthenticated: true, userName: userId },
    state: new Map([['headers', { 'x-client-id': 'client-1' }]]),
  });
}

const config = loadConfig({
  NODE_ENV: 'test',
  DATABASE_URL: 'postgresql://localhost/a2a',
  AMQP_URL: 'amqp://localhost',
  PUBLIC_BASE_URL: 'https://gateway.example/',
  ZITADEL_ISSUER: 'https://identity.example/',
  UNIQUE_CHAT_URL: 'http://node-chat/',
  UNIQUE_SCOPE_MANAGEMENT_URL: 'http://scope-management/',
  UNIQUE_INGESTION_URL: 'http://node-ingestion/',
  ENCRYPTION_KEY: '00'.repeat(32),
});

describe('PgTaskStore', () => {
  it('scopes reads to both company and effective user', async () => {
    const findFirst = vi.fn().mockResolvedValue(undefined);
    const database = { query: { tasks: { findFirst } } } as unknown as GatewayDatabase;
    const store = new PgTaskStore(database, config);

    await store.load('task-1', context('company-1', 'user-1'));
    await store.load('task-1', context('company-2', 'user-2'));

    const firstFilterValues = collectStrings(findFirst.mock.calls[0]?.[0]?.where);
    const secondFilterValues = collectStrings(findFirst.mock.calls[1]?.[0]?.where);
    expect(firstFilterValues).toEqual(expect.arrayContaining(['task-1', 'company-1', 'user-1']));
    expect(firstFilterValues).not.toEqual(expect.arrayContaining(['company-2', 'user-2']));
    expect(secondFilterValues).toEqual(expect.arrayContaining(['task-1', 'company-2', 'user-2']));
  });
});
