import { describe, expect, it, vi } from 'vitest';
import type { GatewayConfig } from '../config/config.js';
import type { UsageRepository } from '../drizzle/usage.repository.js';
import type { AuditLog } from './audit-log.service.js';
import type { GatewayMetrics } from './gateway-metrics.service.js';
import { QuotaExceededError, QuotaService } from './quota.service.js';

function subject(active: { tenant: number; connection: number; tasks: number }) {
  const usage = {
    activeExecutions: vi.fn(async (_companyId: string, connectionId?: string) =>
      connectionId ? active.connection : active.tenant,
    ),
    activeTasks: vi.fn().mockResolvedValue(active.tasks),
  };
  const metrics = { quotaRejected: vi.fn() };
  const audit = { record: vi.fn() };
  const service = new QuotaService(
    usage as unknown as UsageRepository,
    metrics as unknown as GatewayMetrics,
    audit as unknown as AuditLog,
    {
      maxActiveExecutionsPerTenant: 3,
      maxActiveExecutionsPerConnection: 2,
      maxActiveTasksPerTenant: 1,
    } as GatewayConfig,
  );
  return { service, metrics, audit };
}

describe('QuotaService', () => {
  it('admits work below every limit', async () => {
    const { service } = subject({ tenant: 1, connection: 1, tasks: 0 });
    await expect(service.assertOutbound('company-1', 'conn-1')).resolves.toBeUndefined();
    await expect(service.assertInbound('company-1')).resolves.toBeUndefined();
  });

  it.each([
    [{ tenant: 3, connection: 0, tasks: 0 }, 'tenant'],
    [{ tenant: 2, connection: 2, tasks: 0 }, 'connection'],
  ])('rejects outbound work at the %o limit and records it', async (active, scope) => {
    const { service, metrics, audit } = subject(active);
    await expect(service.assertOutbound('company-1', 'conn-1')).rejects.toEqual(
      new QuotaExceededError(scope),
    );
    expect(metrics.quotaRejected).toHaveBeenCalledWith('company-1', 'outbound', scope);
    expect(audit.record).toHaveBeenCalledWith(
      'quota.rejected',
      { companyId: 'company-1' },
      { direction: 'outbound', scope },
    );
  });

  it('rejects inbound tasks over the tenant limit', async () => {
    const { service } = subject({ tenant: 0, connection: 0, tasks: 1 });
    await expect(service.assertInbound('company-1')).rejects.toBeInstanceOf(QuotaExceededError);
  });
});
