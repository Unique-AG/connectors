/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueApiHealth } from '../unique-api-health.service';

vi.mock('undici', () => ({
  fetch: vi.fn(),
}));

import { fetch as undiciFetch } from 'undici';

function createHealthIndicatorService() {
  return {
    check: vi.fn((key: string) => ({
      up: vi.fn((details?: object) => ({ [key]: { status: 'up', ...details } })),
      down: vi.fn((details?: object) => ({ [key]: { status: 'down', ...details } })),
    })),
  };
}

function createAuth(headers: Record<string, string> = { authorization: 'Bearer token' }) {
  return { getAuthHeaders: vi.fn().mockResolvedValue(headers) };
}

function createFailingAuth() {
  return { getAuthHeaders: vi.fn().mockRejectedValue(new Error('auth failed')) };
}

function mockOk() {
  vi.mocked(undiciFetch).mockResolvedValue({
    ok: true,
    status: 200,
    body: { cancel: vi.fn().mockResolvedValue(undefined) },
  } as any);
}

function mockNonOk(status = 503) {
  vi.mocked(undiciFetch).mockResolvedValue({
    ok: false,
    status,
    body: { cancel: vi.fn().mockResolvedValue(undefined) },
  } as any);
}

function mockTimeout() {
  vi.mocked(undiciFetch).mockRejectedValue(
    Object.assign(new DOMException('signal timed out', 'TimeoutError'), {}),
  );
}

describe('UniqueApiHealth', () => {
  let health: UniqueApiHealth;

  beforeEach(() => {
    health = new UniqueApiHealth(createAuth(), 'http://ingestion', 'http://scope-mgmt', 3000);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('checkIngestion', () => {
    it('returns status up when HTTP 200', async () => {
      mockOk();
      const his = createHealthIndicatorService();

      const result = await health.checkIngestion('ingestion', his as any);

      expect(result).toEqual({ ingestion: { status: 'up', ingestion: 'reachable' } });
    });

    it('returns status down with ingestionError HTTP_503 on non-2xx response', async () => {
      mockNonOk(503);
      const his = createHealthIndicatorService();

      const result = await health.checkIngestion('ingestion', his as any);

      expect(result).toEqual({
        ingestion: { status: 'down', ingestion: 'unreachable', ingestionError: 'HTTP_503' },
      });
    });

    it('returns status down with ingestionError TIMEOUT on transport timeout', async () => {
      mockTimeout();
      const his = createHealthIndicatorService();

      const result = await health.checkIngestion('ingestion', his as any);

      expect(result).toEqual({
        ingestion: { status: 'down', ingestion: 'unreachable', ingestionError: 'TIMEOUT' },
      });
    });

    it('returns status down with ingestionError AUTH_FAILURE on auth error', async () => {
      health = new UniqueApiHealth(
        createFailingAuth() as any,
        'http://ingestion',
        'http://scope-mgmt',
        3000,
      );
      const his = createHealthIndicatorService();

      const result = await health.checkIngestion('ingestion', his as any);

      expect(result).toEqual({
        ingestion: { status: 'down', ingestion: 'unreachable', ingestionError: 'AUTH_FAILURE' },
      });
    });
  });

  describe('checkScopeManagement', () => {
    it('returns status up when HTTP 200', async () => {
      mockOk();
      const his = createHealthIndicatorService();

      const result = await health.checkScopeManagement('scopeManagement', his as any);

      expect(result).toEqual({
        scopeManagement: { status: 'up', scopeManagement: 'reachable' },
      });
    });

    it('returns status down with scopeManagementError HTTP_503 on non-2xx response', async () => {
      mockNonOk(503);
      const his = createHealthIndicatorService();

      const result = await health.checkScopeManagement('scopeManagement', his as any);

      expect(result).toEqual({
        scopeManagement: {
          status: 'down',
          scopeManagement: 'unreachable',
          scopeManagementError: 'HTTP_503',
        },
      });
    });

    it('returns status down with scopeManagementError TIMEOUT on transport timeout', async () => {
      mockTimeout();
      const his = createHealthIndicatorService();

      const result = await health.checkScopeManagement('scopeManagement', his as any);

      expect(result).toEqual({
        scopeManagement: {
          status: 'down',
          scopeManagement: 'unreachable',
          scopeManagementError: 'TIMEOUT',
        },
      });
    });

    it('returns status down with scopeManagementError AUTH_FAILURE on auth error', async () => {
      health = new UniqueApiHealth(
        createFailingAuth() as any,
        'http://ingestion',
        'http://scope-mgmt',
        3000,
      );
      const his = createHealthIndicatorService();

      const result = await health.checkScopeManagement('scopeManagement', his as any);

      expect(result).toEqual({
        scopeManagement: {
          status: 'down',
          scopeManagement: 'unreachable',
          scopeManagementError: 'AUTH_FAILURE',
        },
      });
    });
  });
});
