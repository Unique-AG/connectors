import {
  BadRequestException,
  ForbiddenException,
  ServiceUnavailableException,
} from '@nestjs/common';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AuthorizationService } from '../auth/authorization.service.js';
import { loadConfig } from '../config/config.js';
import type { ConnectionRepository, ExecutionRepository } from '../drizzle/gateway.repository.js';
import type { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { ConnectionService } from './connection.service.js';
import { credentialProfile } from './credential-profile.js';
import { CredentialProviderService } from './credential-provider.service.js';
import type { CredentialVault } from './credential-vault.js';
import { EgressService } from './egress.service.js';

const identity = { companyId: 'company-1', userId: 'user-1', roles: [] };
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
  EGRESS_ALLOWED_HOSTS: 'remote.example,oauth.example',
});

function subject(profile: unknown = { type: 'bearer', token: 'remote-secret' }) {
  const row = {
    id: 'conn-1',
    companyId: 'company-1',
    version: 1,
    disabledAt: null,
    agentCardUrl: 'https://remote.example/card',
    credentialType: (profile as { type: string }).type,
    credentialCiphertext: Buffer.from('encrypted'),
    name: 'Remote',
  };
  const connections = {
    find: vi.fn().mockResolvedValue(row),
    findWithCredential: vi.fn().mockResolvedValue(row),
    list: vi.fn().mockResolvedValue([row]),
    create: vi.fn(),
    replace: vi.fn(),
    revoke: vi.fn(),
  };
  const authorization = { assertNewUse: vi.fn(), manageConnections: vi.fn() };
  const unique = {
    getAssistant: vi
      .fn()
      .mockResolvedValue({ id: 'space-1', executionProvider: 'A2A', a2aConnectionId: 'conn-1' }),
  };
  const vault = {
    seal: vi.fn().mockReturnValue(Buffer.from('encrypted')),
    open: vi.fn().mockReturnValue(
      JSON.stringify({
        companyId: 'company-1',
        connectionId: 'conn-1',
        origin: 'https://remote.example',
        profile,
      }),
    ),
  };
  const egress = new EgressService(config);
  const executions = {
    findOwned: vi
      .fn()
      .mockResolvedValue({ assistantId: 'space-1', connectionId: 'conn-1', state: 'working' }),
  };
  return {
    executions,
    row,
    connections,
    authorization,
    unique,
    vault,
    egress,
    provider: new CredentialProviderService(
      connections as unknown as ConnectionRepository,
      authorization as unknown as AuthorizationService,
      unique as unknown as UniqueInternalClient,
      vault as unknown as CredentialVault,
      egress,
      executions as unknown as ExecutionRepository,
    ),
    service: new ConnectionService(
      connections as unknown as ConnectionRepository,
      authorization as unknown as AuthorizationService,
      vault as unknown as CredentialVault,
      egress,
    ),
  };
}

describe('outbound credentials', () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    'authorization',
    'host',
    'cookie',
    'x-user-id',
    'content-length',
    'proxy-authorization',
  ])('rejects an unsafe API key header %s', (header) => {
    expect(credentialProfile.safeParse({ type: 'api_key', header, value: 'secret' }).success).toBe(
      false,
    );
  });

  it.each([
    'http://remote.example',
    'https://evil.example',
    'https://remote.example@evil.example',
    'https://remote.example/#fragment',
  ])('rejects unapproved destination %s', (url) => {
    expect(() => subject().egress.approve(url)).toThrow(BadRequestException);
  });

  it('redacts secrets in management reads and preserves stored connections when disabled', async () => {
    const { service, authorization } = subject();
    authorization.assertNewUse.mockRejectedValue(new ForbiddenException());
    expect(await service.get(identity, 'conn-1')).toEqual({
      id: 'conn-1',
      name: 'Remote',
      agentCardUrl: 'https://remote.example/card',
      credentialType: 'bearer',
      version: 1,
      disabled: false,
      remotePermissions: 'shared',
    });
    await service.revoke(identity, 'conn-1', 1);
    expect(authorization.assertNewUse).not.toHaveBeenCalled();
  });

  it('authorizes and encrypts connection credentials with tenant/connection/destination scope', async () => {
    const { service, vault, connections } = subject();
    await service.save(
      identity,
      { name: 'Remote', agentCardUrl: 'https://remote.example/card', credential: { type: 'none' } },
      { id: 'conn-1', version: 1 },
    );
    expect(JSON.parse(String(vault.seal.mock.calls[0]?.[0]))).toEqual({
      companyId: 'company-1',
      connectionId: 'conn-1',
      origin: 'https://remote.example',
      profile: { type: 'none' },
    });
    expect(connections.replace).toHaveBeenCalledWith(
      'company-1',
      expect.objectContaining({
        credentialCiphertext: Buffer.from('encrypted'),
        credentialType: 'none',
      }),
      1,
    );
  });

  it.each([
    { type: 'none' },
    { type: 'bearer', token: 'remote-secret' },
    { type: 'api_key', header: 'x-api-key', value: 'remote-secret' },
  ])(
    'applies only the explicit $type profile without forwarding Unique identity',
    async (profile) => {
      const { provider } = subject(profile);
      const fetchMock = vi.fn().mockImplementation(async () => Response.json({ ok: true }));
      vi.stubGlobal('fetch', fetchMock);
      await provider.request(identity, 'space-1', 'conn-1', 'https://remote.example/rpc', '{}');
      const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
      expect(init.redirect).toBe('error');
      const headers = new Headers(init.headers);
      expect(headers.has('x-user-id')).toBe(false);
      expect(headers.has('x-company-id')).toBe(false);
      expect(headers.get('authorization')).toBe(
        profile.type === 'bearer' ? 'Bearer remote-secret' : null,
      );
      expect(headers.get('x-api-key')).toBe(profile.type === 'api_key' ? 'remote-secret' : null);
    },
  );

  it('denies a connection belonging to another space or company before decrypting', async () => {
    const { provider, unique, vault } = subject();
    unique.getAssistant.mockResolvedValue({
      id: 'space-1',
      executionProvider: 'A2A',
      a2aConnectionId: 'conn-other',
    });
    await expect(
      provider.request(identity, 'space-1', 'conn-1', 'https://remote.example/rpc'),
    ).rejects.toBeInstanceOf(ForbiddenException);
    expect(vault.open).not.toHaveBeenCalled();
  });

  it('rejects ciphertext copied from another tenant', async () => {
    const { provider } = subject();
    await expect(
      provider.request(
        { ...identity, companyId: 'other' },
        'space-1',
        'conn-1',
        'https://remote.example/rpc',
      ),
    ).rejects.toBeInstanceOf(ForbiddenException);
  });

  it('does not release credentials to another allowlisted origin', async () => {
    const { provider } = subject();
    await expect(
      provider.request(identity, 'space-1', 'conn-1', 'https://oauth.example/rpc'),
    ).rejects.toBeInstanceOf(BadRequestException);
  });

  it('bounds remote response bodies and hides upstream errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('too large')));
    await expect(subject().egress.fetch('https://remote.example', {}, 2)).rejects.toThrow(
      'remote request failed',
    );
  });

  it('caches workload OAuth tokens by connection/version and rechecks revocation on each use', async () => {
    const { provider, connections, row } = subject({
      type: 'oauth2_client_credentials',
      issuer: 'https://oauth.example',
      tokenEndpoint: 'https://oauth.example/token',
      clientId: 'client',
      clientSecret: 'secret',
      authMethod: 'client_secret_basic',
    });
    const fetchMock = vi
      .fn()
      .mockImplementation(async (url: URL) =>
        url.hostname === 'oauth.example'
          ? Response.json({ access_token: 'access', token_type: 'Bearer', expires_in: 3600 })
          : Response.json({ ok: true }),
      );
    vi.stubGlobal('fetch', fetchMock);
    await Promise.all([
      provider.request(identity, 'space-1', 'conn-1', 'https://remote.example/rpc'),
      provider.request(identity, 'space-1', 'conn-1', 'https://remote.example/rpc'),
    ]);
    expect(
      fetchMock.mock.calls.filter(([url]) => (url as URL).hostname === 'oauth.example'),
    ).toHaveLength(1);
    connections.findWithCredential.mockResolvedValue({ ...row, disabledAt: new Date() });
    await expect(
      provider.request(identity, 'space-1', 'conn-1', 'https://remote.example/rpc'),
    ).rejects.toBeInstanceOf(ForbiddenException);
  });

  it('allows only existing active executions to continue after feature disable', async () => {
    const { provider, authorization, executions, unique } = subject();
    authorization.assertNewUse.mockRejectedValue(new ForbiddenException());
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(Response.json({ ok: true }))),
    );
    await expect(
      provider.request(identity, 'space-1', 'conn-1', 'https://remote.example/rpc'),
    ).rejects.toBeInstanceOf(ForbiddenException);
    await provider.request(
      identity,
      'space-1',
      'conn-1',
      'https://remote.example/rpc',
      '{}',
      'exec-1',
    );
    expect(executions.findOwned).toHaveBeenCalledWith(identity, 'exec-1');
    expect(unique.getAssistant).toHaveBeenCalledWith(identity, 'space-1');
    executions.findOwned.mockResolvedValue({
      assistantId: 'space-1',
      connectionId: 'conn-1',
      state: 'completed',
    });
    await expect(
      provider.request(identity, 'space-1', 'conn-1', 'https://remote.example/rpc', '{}', 'exec-1'),
    ).rejects.toBeInstanceOf(ForbiddenException);
  });

  it('does not echo a remote OAuth error or credentials', async () => {
    const { provider } = subject({
      type: 'oauth2_client_credentials',
      issuer: 'https://oauth.example',
      tokenEndpoint: 'https://oauth.example/token',
      clientId: 'client',
      clientSecret: 'secret',
      authMethod: 'client_secret_post',
    });
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ error: 'invalid_client', error_description: 'secret' }, { status: 401 }),
        ),
    );
    await expect(
      provider.request(identity, 'space-1', 'conn-1', 'https://remote.example/rpc'),
    ).rejects.toThrow(new ServiceUnavailableException('remote authentication failed'));
  });
});
