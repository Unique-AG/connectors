import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadConfig } from '../config/config.js';
import { UniqueInternalClient } from './unique-internal.client.js';
import { UniqueInternalError } from './unique-internal.error.js';

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

const identity = { companyId: 'company-1', userId: 'user-1', roles: ['SPACE_MANAGER'] };

describe('UniqueInternalClient', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('forwards only the effective human identity to internal services', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { message: { id: 'message-1' } } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await new UniqueInternalClient(config).getMessage(
      identity,
      'chat-1',
      'message-1',
    );

    expect(result).toEqual({ id: 'message-1' });
    const [, request] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(request.headers).toEqual({
      'content-type': 'application/json',
      'x-company-id': 'company-1',
      'x-user-id': 'user-1',
    });
    expect(request.headers).not.toHaveProperty('x-service-id');
  });

  it('uses the existing object-authorized core management query', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(Response.json({ data: { assistantByCompany: { id: 'assistant-1' } } }));
    vi.stubGlobal('fetch', fetchMock);
    await new UniqueInternalClient(config).verifySpaceManagement(identity, 'assistant-1');
    const [url, request] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.toString()).toBe('http://node-chat/graphql');
    expect(JSON.parse(String(request.body))).toEqual({
      query:
        'query A2aManagedAssistant($assistantId: String!) { assistantByCompany(assistantId: $assistantId) { id name executionProvider } }',
      variables: { assistantId: 'assistant-1' },
    });
    expect(request.headers).not.toHaveProperty('x-user-roles');
    expect(request.redirect).toBe('error');
  });

  it('normalizes authorization errors without retrying them', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 403 })));

    await expect(
      new UniqueInternalClient(config).getAssistant(identity, 'assistant-1'),
    ).rejects.toEqual(
      expect.objectContaining<Partial<UniqueInternalError>>({
        code: 'UNAUTHORIZED',
        retryable: false,
      }),
    );
  });
});
