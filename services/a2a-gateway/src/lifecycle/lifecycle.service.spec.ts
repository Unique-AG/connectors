import { describe, expect, it, vi } from 'vitest';
import type { GatewayConfig } from '../config/config.js';
import type { PublicationRepository } from '../drizzle/publication.repository.js';
import type { RetentionRepository } from '../drizzle/retention.repository.js';
import type { AuditLog } from '../observability/audit-log.service.js';
import type { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { UniqueInternalError } from '../unique/unique-internal.error.js';
import type { MaintenanceService } from '../workflow/maintenance.service.js';
import { LifecycleService } from './lifecycle.service.js';

function subject() {
  const retention = {
    purgeTasks: vi.fn().mockResolvedValue(0),
    purgeContexts: vi.fn().mockResolvedValue(0),
    purgeExecutions: vi.fn().mockResolvedValue(0),
    purgeRemoteContexts: vi.fn().mockResolvedValue(0),
    purgeUnboundConnections: vi.fn().mockResolvedValue(0),
    enabledPublications: vi.fn().mockResolvedValue([
      { id: 'pub-1', companyId: 'company-1', assistantId: 'gone', createdByUserId: 'admin-1' },
      { id: 'pub-2', companyId: 'company-1', assistantId: 'denied', createdByUserId: 'admin-1' },
      { id: 'pub-3', companyId: 'company-1', assistantId: 'down', createdByUserId: 'admin-1' },
    ]),
  };
  const publications = { disable: vi.fn() };
  const unique = {
    verifySpaceManagement: vi.fn(async (_identity: unknown, assistantId: string) => {
      if (assistantId === 'gone') {
        throw new UniqueInternalError('missing', 'NOT_FOUND', false);
      }
      if (assistantId === 'denied') {
        throw new UniqueInternalError('denied', 'UNAUTHORIZED', false);
      }
      throw new UniqueInternalError('down', 'UNAVAILABLE', true);
    }),
  };
  const service = new LifecycleService(
    retention as unknown as RetentionRepository,
    publications as unknown as PublicationRepository,
    unique as unknown as UniqueInternalClient,
    { register: vi.fn() } as unknown as MaintenanceService,
    { record: vi.fn() } as unknown as AuditLog,
    { taskRetentionDays: 30 } as GatewayConfig,
  );
  return { service, retention, publications, unique };
}

describe('LifecycleService', () => {
  it('disables only publications whose space core reports as deleted', async () => {
    const { service, publications, unique } = subject();
    await service.reconcilePublications();
    expect(unique.verifySpaceManagement).toHaveBeenCalledWith(
      { companyId: 'company-1', userId: 'admin-1', roles: [] },
      'gone',
    );
    expect(publications.disable).toHaveBeenCalledTimes(1);
    expect(publications.disable).toHaveBeenCalledWith('company-1', 'gone');
  });

  it('purges every kind of expired gateway state with bounded batches', async () => {
    const { service, retention } = subject();
    await service.purge();
    for (const purge of [
      retention.purgeTasks,
      retention.purgeContexts,
      retention.purgeExecutions,
      retention.purgeRemoteContexts,
      retention.purgeUnboundConnections,
    ]) {
      expect(purge).toHaveBeenCalledWith(expect.any(Date), 500);
    }
    const idleBefore = retention.purgeContexts.mock.calls[0]?.[0] as Date;
    expect(Date.now() - idleBefore.getTime()).toBeGreaterThanOrEqual(30 * 86_400_000 - 1_000);
  });
});
