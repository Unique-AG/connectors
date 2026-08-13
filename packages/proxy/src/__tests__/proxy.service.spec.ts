import { readFileSync } from 'node:fs';
import { Redacted } from '@unique-ag/utils';
import type { ConfigService } from '@nestjs/config';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProxyConfigNamespaced } from '../proxy.config';
import type { ProxyModuleOptions } from '../proxy.module-definition';

const mockAgentInstances: Array<{ close: ReturnType<typeof vi.fn> }> = [];
const mockProxyAgentInstances: Array<{ close: ReturnType<typeof vi.fn> }> = [];
const mockHttpsProxyAgentInstances: Array<{ destroy: ReturnType<typeof vi.fn> }> = [];

const sharedTimeoutOptions = {
  bodyTimeout: 60_000,
  headersTimeout: 30_000,
  connectTimeout: 15_000,
};

vi.mock('undici', () => ({
  Agent: vi.fn().mockImplementation(() => {
    const inst = { close: vi.fn() };
    mockAgentInstances.push(inst);
    return inst;
  }),
  ProxyAgent: vi.fn().mockImplementation(() => {
    const inst = { close: vi.fn() };
    mockProxyAgentInstances.push(inst);
    return inst;
  }),
}));

vi.mock('https-proxy-agent', () => ({
  HttpsProxyAgent: vi.fn().mockImplementation(() => {
    const inst = { destroy: vi.fn() };
    mockHttpsProxyAgentInstances.push(inst);
    return inst;
  }),
}));

vi.mock('node:fs', () => ({
  readFileSync: vi.fn().mockReturnValue(Buffer.from('fake-cert')),
}));

import { HttpsProxyAgent } from 'https-proxy-agent';
import { Agent, ProxyAgent } from 'undici';
import { ProxyService } from '../proxy.service';

function makeConfigService(proxyConfig: Record<string, unknown>) {
  return {
    get: vi.fn().mockReturnValue(proxyConfig),
  } as unknown as ConfigService<ProxyConfigNamespaced, true>;
}

function createService(
  proxyConfig: Record<string, unknown>,
  options: ProxyModuleOptions = { isExternal: false },
) {
  return new ProxyService(options, makeConfigService(proxyConfig));
}

describe('ProxyService', () => {
  beforeEach(() => {
    mockAgentInstances.length = 0;
    mockProxyAgentInstances.length = 0;
    mockHttpsProxyAgentInstances.length = 0;
    vi.clearAllMocks();
  });

  describe('getDispatcher', () => {
    it('returns distinct Agent dispatchers for never and always when authMode is none', () => {
      const service = createService({ authMode: 'none' });
      const neverDispatcher = service.getDispatcher({ mode: 'never' });
      const alwaysDispatcher = service.getDispatcher({ mode: 'always' });

      expect(neverDispatcher).not.toBe(alwaysDispatcher);
      expect(vi.mocked(ProxyAgent)).not.toHaveBeenCalled();
      expect(vi.mocked(Agent)).toHaveBeenCalledTimes(2);
      expect(vi.mocked(Agent)).toHaveBeenCalledWith(sharedTimeoutOptions);
    });

    it('returns the ProxyAgent dispatcher when mode is "always" and proxy is configured', () => {
      const service = createService({
        authMode: 'no_auth',
        host: 'proxy.example.com',
        port: 8080,
        protocol: 'http',
      });

      expect(mockProxyAgentInstances).toHaveLength(1);
      expect(service.getDispatcher({ mode: 'always' })).toBe(mockProxyAgentInstances[0]);
    });

    it('no-proxy dispatcher is distinct from proxy dispatcher', () => {
      const service = createService({
        authMode: 'no_auth',
        host: 'proxy.example.com',
        port: 8080,
        protocol: 'http',
      });

      expect(service.getDispatcher({ mode: 'never' })).not.toBe(
        service.getDispatcher({ mode: 'always' }),
      );
    });

    it('returns the proxy dispatcher when mode is "for-external-only" and isExternal is true', () => {
      const service = createService(
        {
          authMode: 'no_auth',
          host: 'proxy.example.com',
          port: 8080,
          protocol: 'http',
        },
        { isExternal: true },
      );

      expect(mockProxyAgentInstances).toHaveLength(1);
      expect(service.getDispatcher({ mode: 'for-external-only' })).toBe(mockProxyAgentInstances[0]);
    });

    it('returns the no-proxy dispatcher when mode is "for-external-only" and isExternal is false', () => {
      const service = createService(
        {
          authMode: 'no_auth',
          host: 'proxy.example.com',
          port: 8080,
          protocol: 'http',
        },
        { isExternal: false },
      );

      const neverDispatcher = service.getDispatcher({ mode: 'never' });
      expect(service.getDispatcher({ mode: 'for-external-only' })).toBe(neverDispatcher);
      expect(service.getDispatcher({ mode: 'for-external-only' })).not.toBe(
        service.getDispatcher({ mode: 'always' }),
      );
    });
  });

  describe('createDispatcher', () => {
    it('creates a ProxyAgent with Basic token for username_password auth', () => {
      createService({
        authMode: 'username_password',
        host: 'proxy.example.com',
        port: 3128,
        protocol: 'http',
        username: new Redacted('alice'),
        password: new Redacted('s3cr3t'),
      });

      const credentials = Buffer.from('alice:s3cr3t').toString('base64');
      expect(vi.mocked(ProxyAgent)).toHaveBeenCalledWith(
        expect.objectContaining({
          ...sharedTimeoutOptions,
          token: `Basic ${credentials}`,
        }),
      );
    });

    it('creates a ProxyAgent with correct URI and shared timeouts for no_auth proxy', () => {
      createService({
        authMode: 'no_auth',
        host: 'proxy.internal',
        port: 8080,
        protocol: 'https',
      });

      expect(vi.mocked(Agent)).toHaveBeenCalledWith(sharedTimeoutOptions);
      expect(vi.mocked(ProxyAgent)).toHaveBeenCalledWith(
        expect.objectContaining({
          ...sharedTimeoutOptions,
          uri: 'https://proxy.internal:8080',
        }),
      );
    });

    it('attaches custom headers to ProxyAgent when headers are configured', () => {
      createService({
        authMode: 'no_auth',
        host: 'proxy.example.com',
        port: 8080,
        protocol: 'http',
        headers: { 'X-Proxy-Token': 'abc123' },
      });

      expect(vi.mocked(ProxyAgent)).toHaveBeenCalledWith(
        expect.objectContaining({ headers: { 'X-Proxy-Token': 'abc123' } }),
      );
    });

    it('clones PROXY_HEADERS so ProxyAgent and HttpsProxyAgent do not share the same object', () => {
      const headers = { 'X-Proxy-Token': 'abc123' };
      createService({
        authMode: 'username_password',
        host: 'proxy.example.com',
        port: 3128,
        protocol: 'http',
        username: new Redacted('alice'),
        password: new Redacted('s3cr3t'),
        headers,
      });

      const proxyAgentArg = vi.mocked(ProxyAgent).mock.calls[0]?.[0];
      expect(proxyAgentArg).toEqual(expect.objectContaining({ headers }));
      const proxyAgentHeaders = (proxyAgentArg as { headers: Record<string, string> }).headers;
      const httpsAgentHeaders = vi.mocked(HttpsProxyAgent).mock.calls[0]?.[1]?.headers as Record<
        string,
        string
      >;

      expect(proxyAgentHeaders).toEqual(headers);
      expect(httpsAgentHeaders).toEqual(headers);
      expect(proxyAgentHeaders).not.toBe(headers);
      expect(httpsAgentHeaders).not.toBe(headers);
      expect(proxyAgentHeaders).not.toBe(httpsAgentHeaders);

      proxyAgentHeaders['proxy-authorization'] = 'Basic from-undici';
      expect(httpsAgentHeaders).toEqual(headers);
      expect(headers).toEqual({ 'X-Proxy-Token': 'abc123' });
    });

    it('populates proxyTls with cert and key for ssl_tls auth', () => {
      createService({
        authMode: 'ssl_tls',
        host: 'proxy.example.com',
        port: 8443,
        protocol: 'https',
        sslCertPath: '/certs/client.crt',
        sslKeyPath: '/certs/client.key',
      });

      expect(vi.mocked(readFileSync)).toHaveBeenCalledWith('/certs/client.crt');
      expect(vi.mocked(readFileSync)).toHaveBeenCalledWith('/certs/client.key');
      expect(vi.mocked(ProxyAgent)).toHaveBeenCalledWith(
        expect.objectContaining({
          proxyTls: {
            cert: Buffer.from('fake-cert'),
            key: Buffer.from('fake-cert'),
          },
        }),
      );
    });

    it('populates proxyTls with cert, key, and ca when ssl_tls has sslCaBundlePath', () => {
      createService({
        authMode: 'ssl_tls',
        host: 'proxy.example.com',
        port: 8443,
        protocol: 'https',
        sslCertPath: '/certs/client.crt',
        sslKeyPath: '/certs/client.key',
        sslCaBundlePath: '/certs/ca.pem',
      });

      expect(vi.mocked(readFileSync)).toHaveBeenCalledWith('/certs/client.crt');
      expect(vi.mocked(readFileSync)).toHaveBeenCalledWith('/certs/client.key');
      expect(vi.mocked(readFileSync)).toHaveBeenCalledWith('/certs/ca.pem');
      expect(vi.mocked(ProxyAgent)).toHaveBeenCalledWith(
        expect.objectContaining({
          proxyTls: {
            ca: Buffer.from('fake-cert'),
            cert: Buffer.from('fake-cert'),
            key: Buffer.from('fake-cert'),
          },
        }),
      );
    });

    it('populates proxyTls.ca when sslCaBundlePath is set on no_auth', () => {
      createService({
        authMode: 'no_auth',
        host: 'proxy.example.com',
        port: 8080,
        protocol: 'https',
        sslCaBundlePath: '/certs/ca.pem',
      });

      expect(vi.mocked(readFileSync)).toHaveBeenCalledWith('/certs/ca.pem');
      expect(vi.mocked(ProxyAgent)).toHaveBeenCalledWith(
        expect.objectContaining({
          proxyTls: { ca: Buffer.from('fake-cert') },
        }),
      );
    });
  });

  describe('getHttpAgent', () => {
    it('returns undefined when mode is "never"', () => {
      const service = createService({
        authMode: 'no_auth',
        host: 'proxy.example.com',
        port: 8080,
        protocol: 'http',
      });

      expect(service.getHttpAgent({ mode: 'never' })).toBeUndefined();
    });

    it('returns undefined when authMode is "none" even if mode is "always"', () => {
      const service = createService({ authMode: 'none' });

      expect(service.getHttpAgent({ mode: 'always' })).toBeUndefined();
    });

    it('returns undefined when mode is "for-external-only" and isExternal is false', () => {
      const service = createService(
        {
          authMode: 'no_auth',
          host: 'proxy.example.com',
          port: 8080,
          protocol: 'http',
        },
        { isExternal: false },
      );

      expect(service.getHttpAgent({ mode: 'for-external-only' })).toBeUndefined();
    });

    it('returns HttpsProxyAgent for no_auth when mode is "always"', () => {
      const service = createService({
        authMode: 'no_auth',
        host: 'proxy.example.com',
        port: 8080,
        protocol: 'http',
      });

      expect(mockHttpsProxyAgentInstances).toHaveLength(1);
      expect(service.getHttpAgent({ mode: 'always' })).toBe(mockHttpsProxyAgentInstances[0]);
      expect(vi.mocked(HttpsProxyAgent)).toHaveBeenCalledWith(
        'http://proxy.example.com:8080',
        expect.any(Object),
      );
    });

    it('returns HttpsProxyAgent for username_password when mode is "always"', () => {
      const service = createService({
        authMode: 'username_password',
        host: 'proxy.example.com',
        port: 3128,
        protocol: 'http',
        username: new Redacted('alice'),
        password: new Redacted('s3cr3t'),
      });

      expect(mockHttpsProxyAgentInstances).toHaveLength(1);
      expect(service.getHttpAgent({ mode: 'always' })).toBe(mockHttpsProxyAgentInstances[0]);
    });

    it('returns HttpsProxyAgent for ssl_tls when mode is "always"', () => {
      const service = createService({
        authMode: 'ssl_tls',
        host: 'proxy.example.com',
        port: 8443,
        protocol: 'https',
        sslCertPath: '/certs/client.crt',
        sslKeyPath: '/certs/client.key',
      });

      expect(mockHttpsProxyAgentInstances).toHaveLength(1);
      expect(service.getHttpAgent({ mode: 'always' })).toBe(mockHttpsProxyAgentInstances[0]);
    });

    it('returns HttpsProxyAgent when mode is "for-external-only" and isExternal is true', () => {
      const service = createService(
        {
          authMode: 'no_auth',
          host: 'proxy.example.com',
          port: 8080,
          protocol: 'http',
        },
        { isExternal: true },
      );

      expect(mockHttpsProxyAgentInstances).toHaveLength(1);
      expect(service.getHttpAgent({ mode: 'for-external-only' })).toBe(
        mockHttpsProxyAgentInstances[0],
      );
    });

    it('calls HttpsProxyAgent with authenticated URL for username_password', () => {
      createService({
        authMode: 'username_password',
        host: 'proxy.example.com',
        port: 3128,
        protocol: 'http',
        username: new Redacted('alice@corp'),
        password: new Redacted('p@ss:word'),
      });

      expect(vi.mocked(HttpsProxyAgent)).toHaveBeenCalledWith(
        `http://${encodeURIComponent('alice@corp')}:${encodeURIComponent('p@ss:word')}@proxy.example.com:3128`,
        expect.any(Object),
      );
    });

    it('passes ssl_tls cert, key, ca, and headers to HttpsProxyAgent options', () => {
      createService({
        authMode: 'ssl_tls',
        host: 'proxy.example.com',
        port: 8443,
        protocol: 'https',
        sslCertPath: '/certs/client.crt',
        sslKeyPath: '/certs/client.key',
        sslCaBundlePath: '/certs/ca.pem',
        headers: { 'X-Proxy-Token': 'abc123' },
      });

      expect(vi.mocked(readFileSync)).toHaveBeenCalledWith('/certs/client.crt');
      expect(vi.mocked(readFileSync)).toHaveBeenCalledWith('/certs/client.key');
      expect(vi.mocked(readFileSync)).toHaveBeenCalledWith('/certs/ca.pem');
      expect(vi.mocked(HttpsProxyAgent)).toHaveBeenCalledWith('https://proxy.example.com:8443', {
        ca: Buffer.from('fake-cert'),
        cert: Buffer.from('fake-cert'),
        key: Buffer.from('fake-cert'),
        headers: { 'X-Proxy-Token': 'abc123' },
      });
    });
  });

  describe('onModuleDestroy', () => {
    it('closes both Agent dispatchers when authMode is none', async () => {
      const service = createService({ authMode: 'none' });
      const noProxyDispatcher = service.getDispatcher({ mode: 'never' });
      const proxyDispatcher = service.getDispatcher({ mode: 'always' });

      expect(noProxyDispatcher).not.toBe(proxyDispatcher);

      await service.onModuleDestroy();

      expect(noProxyDispatcher.close).toHaveBeenCalledTimes(1);
      expect(proxyDispatcher.close).toHaveBeenCalledTimes(1);
    });

    it('closes ProxyAgent and no-proxy Agent when proxy is configured', async () => {
      const service = createService({
        authMode: 'no_auth',
        host: 'proxy.example.com',
        port: 8080,
        protocol: 'http',
      });

      expect(mockAgentInstances).toHaveLength(1);
      expect(mockProxyAgentInstances).toHaveLength(1);

      const noProxyDispatcher = service.getDispatcher({ mode: 'never' });
      const proxyDispatcher = service.getDispatcher({ mode: 'always' });

      await service.onModuleDestroy();

      expect(noProxyDispatcher.close).toHaveBeenCalledTimes(1);
      expect(proxyDispatcher.close).toHaveBeenCalledTimes(1);
    });

    it('destroys the httpAgent when present', async () => {
      const service = createService({
        authMode: 'no_auth',
        host: 'proxy.example.com',
        port: 8080,
        protocol: 'http',
      });

      expect(mockHttpsProxyAgentInstances).toHaveLength(1);
      const httpAgent = service.getHttpAgent({ mode: 'always' });

      await service.onModuleDestroy();

      expect(httpAgent?.destroy).toHaveBeenCalledTimes(1);
    });
  });
});
