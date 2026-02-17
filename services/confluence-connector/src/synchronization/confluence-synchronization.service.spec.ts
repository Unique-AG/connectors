import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfluenceAuth } from '../auth/confluence-auth';
import { ServiceRegistry } from '../tenant/service-registry';
import type { TenantContext } from '../tenant/tenant-context.interface';
import { tenantStorage } from '../tenant/tenant-context.storage';
import { smear } from '../utils/logging.util';
import { ConfluenceSynchronizationService } from './confluence-synchronization.service';

const mockTenantLogger = vi.hoisted(() => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
}));

function createMockAuth(): ConfluenceAuth {
  return {
    acquireToken: vi.fn().mockResolvedValue('mock-token-12345678'),
  } as ConfluenceAuth;
}

function createMockTenant(name: string, overrides: Partial<TenantContext> = {}): TenantContext {
  return {
    name,
    config: {
      processing: { scanIntervalCron: '*/5 * * * *' },
    },
    isScanning: false,
    ...overrides,
  } as unknown as TenantContext;
}

function createService(tenant: TenantContext, mockAuth: ConfluenceAuth) {
  const serviceRegistry = new ServiceRegistry();
  const mockBaseLogger = { child: () => mockTenantLogger };
  serviceRegistry.registerTenantLogger(tenant.name, mockBaseLogger as never);
  serviceRegistry.register(tenant.name, ConfluenceAuth, mockAuth);

  return tenantStorage.run(tenant, () => new ConfluenceSynchronizationService(serviceRegistry));
}

describe('ConfluenceSynchronizationService', () => {
  let tenant: TenantContext;
  let mockAuth: ConfluenceAuth;
  let service: ConfluenceSynchronizationService;

  beforeEach(() => {
    vi.clearAllMocks();
    tenant = createMockTenant('test-tenant');
    mockAuth = createMockAuth();
    service = createService(tenant, mockAuth);
  });

  describe('synchronize', () => {
    it('logs start and completion messages', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Starting sync');
      expect(mockTenantLogger.info).toHaveBeenCalledWith('Sync completed');
    });

    it('acquires a token and logs the smeared value', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockAuth.acquireToken).toHaveBeenCalledOnce();
      expect(mockTenantLogger.info).toHaveBeenCalledWith(
        { token: smear('mock-token-12345678') },
        'Token acquired',
      );
    });

    it('skips when tenant is already scanning', async () => {
      tenant.isScanning = true;

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Sync already in progress, skipping');
      expect(mockAuth.acquireToken).not.toHaveBeenCalled();
    });

    it('resets isScanning after successful sync', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
    });

    it('resets isScanning after failed sync', async () => {
      vi.mocked(mockAuth.acquireToken).mockRejectedValue(new Error('auth failure'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
    });

    it('logs the error when token acquisition fails', async () => {
      vi.mocked(mockAuth.acquireToken).mockRejectedValue(new Error('auth failure'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockTenantLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ msg: 'Sync failed', error: expect.anything() }),
      );
    });
  });
});
