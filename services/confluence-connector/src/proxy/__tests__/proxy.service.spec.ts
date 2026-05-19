import type { ConfigService } from '@nestjs/config';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockAgentInstances: Array<{ close: ReturnType<typeof vi.fn> }> = [];
const mockProxyAgentInstances: Array<{ close: ReturnType<typeof vi.fn> }> = [];

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

vi.mock('node:fs', () => ({
  readFileSync: vi.fn().mockReturnValue(Buffer.from('fake-cert')),
}));

import { ProxyAgent } from 'undici';
import { Redacted } from '../../utils/redacted';
import { ProxyService } from '../proxy.service';

function makeConfigService(proxyConfig: Record<string, unknown>) {
  return {
    get: vi.fn().mockReturnValue(proxyConfig),
  } as unknown as ConfigService<Record<string, unknown>, true>;
}

describe('ProxyService', () => {
  beforeEach(() => {
    mockAgentInstances.length = 0;
    mockProxyAgentInstances.length = 0;
    vi.clearAllMocks();
  });

  describe('getDispatcher', () => {
    it('returns the no-proxy dispatcher when mode is "never"', () => {
      const service = new ProxyService(makeConfigService({ authMode: 'none' }));

      const [noProxyDispatcher] = mockAgentInstances;
      expect(service.getDispatcher({ mode: 'never' })).toBe(noProxyDispatcher);
    });

    it('returns the proxy dispatcher when mode is "always" and authMode is "none"', () => {
      const service = new ProxyService(makeConfigService({ authMode: 'none' }));

      const [, proxyDispatcher] = mockAgentInstances;
      expect(service.getDispatcher({ mode: 'always' })).toBe(proxyDispatcher);
    });

    it('returns the ProxyAgent dispatcher when mode is "always" and proxy is configured', () => {
      const service = new ProxyService(
        makeConfigService({
          authMode: 'no_auth',
          host: 'proxy.example.com',
          port: 8080,
          protocol: 'http',
        }),
      );

      const [proxyAgentDispatcher] = mockProxyAgentInstances;
      expect(service.getDispatcher({ mode: 'always' })).toBe(proxyAgentDispatcher);
    });

    it('no-proxy dispatcher is distinct from proxy dispatcher', () => {
      const service = new ProxyService(
        makeConfigService({
          authMode: 'no_auth',
          host: 'proxy.example.com',
          port: 8080,
          protocol: 'http',
        }),
      );

      expect(service.getDispatcher({ mode: 'never' })).not.toBe(
        service.getDispatcher({ mode: 'always' }),
      );
    });
  });

  describe('createDispatcher', () => {
    it('creates a ProxyAgent with Basic token for username_password auth', () => {
      new ProxyService(
        makeConfigService({
          authMode: 'username_password',
          host: 'proxy.example.com',
          port: 3128,
          protocol: 'http',
          username: 'alice',
          password: new Redacted('s3cr3t'),
        }),
      );

      const credentials = Buffer.from('alice:s3cr3t').toString('base64');
      expect(vi.mocked(ProxyAgent)).toHaveBeenCalledWith(
        expect.objectContaining({ token: `Basic ${credentials}` }),
      );
    });

    it('creates a ProxyAgent with correct URI for no_auth proxy', () => {
      new ProxyService(
        makeConfigService({
          authMode: 'no_auth',
          host: 'proxy.internal',
          port: 8080,
          protocol: 'https',
        }),
      );

      expect(vi.mocked(ProxyAgent)).toHaveBeenCalledWith(
        expect.objectContaining({ uri: 'https://proxy.internal:8080' }),
      );
    });

    it('attaches custom headers to ProxyAgent when headers are configured', () => {
      new ProxyService(
        makeConfigService({
          authMode: 'no_auth',
          host: 'proxy.example.com',
          port: 8080,
          protocol: 'http',
          headers: { 'X-Proxy-Token': 'abc123' },
        }),
      );

      expect(vi.mocked(ProxyAgent)).toHaveBeenCalledWith(
        expect.objectContaining({ headers: { 'X-Proxy-Token': 'abc123' } }),
      );
    });
  });

  describe('onModuleDestroy', () => {
    it('closes both the proxy and no-proxy dispatchers', async () => {
      const service = new ProxyService(makeConfigService({ authMode: 'none' }));
      const noProxy = mockAgentInstances[0];
      const proxy = mockAgentInstances[1];

      await service.onModuleDestroy();

      expect(noProxy?.close).toHaveBeenCalledTimes(1);
      expect(proxy?.close).toHaveBeenCalledTimes(1);
    });
  });
});
