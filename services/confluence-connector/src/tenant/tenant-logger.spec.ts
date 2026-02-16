import type pino from 'pino';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TenantContext } from './tenant-context.interface';
import { tenantStorage } from './tenant-context.storage';

const { mockChildLogger, mockRoot } = vi.hoisted(() => {
  const mockChildLogger = { info: vi.fn(), error: vi.fn() } as unknown as pino.Logger;
  const mockRoot = {
    child: vi.fn().mockReturnValue(mockChildLogger),
  } as unknown as pino.Logger;
  return { mockChildLogger, mockRoot };
});

vi.mock('nestjs-pino', async () => {
  const actual = await vi.importActual('nestjs-pino');
  return {
    ...actual,
    PinoLogger: { root: mockRoot },
  };
});

import { getTenantLogger } from './tenant-logger';

describe('getTenantLogger', () => {
  const mockTenant = { name: 'acme' } as TenantContext;
  const service = { name: 'ConfluenceSyncService' } as const;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('throws when called outside of tenant context', () => {
    expect(() => getTenantLogger(service)).toThrow(
      'No tenant context — called outside of sync execution',
    );
  });

  it('calls PinoLogger.root.child with tenantName and service bindings', () => {
    tenantStorage.run(mockTenant, () => {
      getTenantLogger(service);

      expect(mockRoot.child).toHaveBeenCalledWith({
        tenantName: 'acme',
        service: 'ConfluenceSyncService',
      });
    });
  });

  it('returns the child logger', () => {
    tenantStorage.run(mockTenant, () => {
      const logger = getTenantLogger(service);

      expect(logger).toBe(mockChildLogger);
    });
  });
});
