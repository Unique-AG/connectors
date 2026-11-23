import { TestBed } from '@suites/unit';
import { describe, expect, it } from 'vitest';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';
import { FlowBindingService } from './flow-binding.service';

const createService = async (overrides: Partial<McpOAuthModuleOptions> = {}) => {
  const { unit } = await TestBed.solitary(FlowBindingService)
    .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    .impl(
      () =>
        ({
          hmacSecret: 'test-hmac-secret',
          serverUrl: 'https://mcp.example.com',
          oauthSessionExpiresIn: 600000,
          ...overrides,
        }) as McpOAuthModuleOptions,
    )
    .compile();
  return unit;
};

const cookieHeader = (name: string, value: string) => `other=1; ${name}=${value}; theme=dark`;

describe('FlowBindingService', () => {
  describe('createBinding', () => {
    it('issues a host-only, HttpOnly, Secure, SameSite=Lax cookie on https', async () => {
      const service = await createService();

      const { cookie } = service.createBinding('session-123');

      expect(cookie.name).toMatch(/^__Host-mcp_oauth_flow_[0-9a-f]{16}$/);
      expect(cookie.options).toEqual({
        httpOnly: true,
        secure: true,
        sameSite: 'lax',
        path: '/',
        maxAge: 600000,
      });
    });

    it('drops Secure and the __Host- prefix on a plain-http server', async () => {
      const service = await createService({ serverUrl: 'http://localhost:3000' });

      const { cookie } = service.createBinding('session-123');

      expect(cookie.name).toMatch(/^mcp_oauth_flow_[0-9a-f]{16}$/);
      expect(cookie.options.secure).toBe(false);
    });

    it('issues a different cookie name per session', async () => {
      const service = await createService();

      expect(service.createBinding('session-a').cookie.name).not.toBe(
        service.createBinding('session-b').cookie.name,
      );
    });
  });

  describe('readBinding', () => {
    it('returns the cookie value for a validly signed cookie', async () => {
      const service = await createService();
      const { cookie } = service.createBinding('session-123');

      expect(service.readBinding(cookieHeader(cookie.name, cookie.value), 'session-123')).toBe(
        cookie.value,
      );
    });

    it('rejects a missing cookie header', async () => {
      const service = await createService();

      expect(service.readBinding(undefined, 'session-123')).toBeUndefined();
    });

    it('rejects a cookie issued for another session', async () => {
      const service = await createService();
      const other = service.createBinding('session-other').cookie;
      const { cookie } = service.createBinding('session-123');

      expect(
        service.readBinding(cookieHeader(cookie.name, other.value), 'session-123'),
      ).toBeUndefined();
    });

    it('rejects a cookie with a tampered signature', async () => {
      const service = await createService();
      const { cookie } = service.createBinding('session-123');
      const [binding] = cookie.value.split('.');

      expect(
        service.readBinding(cookieHeader(cookie.name, `${binding}.forged`), 'session-123'),
      ).toBeUndefined();
    });

    it('rejects a cookie signed with another secret', async () => {
      const attacker = await createService({ hmacSecret: 'attacker-secret' });
      const service = await createService();
      const { cookie } = attacker.createBinding('session-123');

      expect(
        service.readBinding(cookieHeader(cookie.name, cookie.value), 'session-123'),
      ).toBeUndefined();
    });
  });

  describe('isValidCsrfToken', () => {
    it('accepts the token issued with the cookie', async () => {
      const service = await createService();
      const { cookie, csrfToken } = service.createBinding('session-123');

      expect(service.isValidCsrfToken('session-123', cookie.value, csrfToken)).toBe(true);
    });

    it('rejects a token issued with another cookie', async () => {
      const service = await createService();
      const { cookie } = service.createBinding('session-123');
      const { csrfToken } = service.createBinding('session-123');

      expect(service.isValidCsrfToken('session-123', cookie.value, csrfToken)).toBe(false);
    });

    it('rejects a token of a different length', async () => {
      const service = await createService();
      const { cookie } = service.createBinding('session-123');

      expect(service.isValidCsrfToken('session-123', cookie.value, 'short')).toBe(false);
    });
  });

  describe('clearedCookie', () => {
    it('names the session cookie without a lifetime', async () => {
      const service = await createService();
      const { cookie } = service.createBinding('session-123');

      expect(service.clearedCookie('session-123')).toEqual({
        name: cookie.name,
        options: { httpOnly: true, secure: true, sameSite: 'lax', path: '/' },
      });
    });
  });
});
