/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DelegatedAccessRecoverySchedulerService } from './delegated-access-recovery-scheduler.service';

const NOW = new Date('2026-11-24T00:40:00.000Z');
const CYCLE_STARTED_AT = new Date('2026-11-24T00:00:00.000Z');

const discoveryState = (payload: Record<string, unknown>) => ({
  dataType: 'DelegatedAccessDiscovery',
  payload,
});

describe('DelegatedAccessRecoverySchedulerService', () => {
  let amqp: { publish: ReturnType<typeof vi.fn> };
  let persistentCacheService: { get: ReturnType<typeof vi.fn> };
  let discoverCommand: { hasPendingDelegates: ReturnType<typeof vi.fn> };
  let service: DelegatedAccessRecoverySchedulerService;

  beforeEach(() => {
    vi.useFakeTimers({ now: NOW, toFake: ['Date'] });
    amqp = { publish: vi.fn().mockResolvedValue(undefined) };
    persistentCacheService = { get: vi.fn() };
    discoverCommand = { hasPendingDelegates: vi.fn().mockResolvedValue(false) };
    service = new DelegatedAccessRecoverySchedulerService(
      { addCronJob: vi.fn(), getCronJob: vi.fn() } as any,
      amqp as any,
      { scan: 'full_access_only', recoveryCronSchedule: '*/30 * * * *' } as any,
      persistentCacheService as any,
      discoverCommand as any,
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const publishedDiscoveryEvent = () =>
    expect.objectContaining({
      type: 'unique.outlook-semantic-mcp.delegated-access.discover',
      payload: { newCycle: false },
    });

  it('resumes a failed discovery within its cycle', async () => {
    persistentCacheService.get.mockResolvedValue(
      discoveryState({
        state: 'failed',
        cycleStartedAt: CYCLE_STARTED_AT.getTime(),
        lastProgressRegisteredAt: CYCLE_STARTED_AT.getTime(),
      }),
    );

    await service.runRecovery();

    expect(amqp.publish).toHaveBeenCalledWith(
      expect.any(String),
      'unique.outlook-semantic-mcp.delegated-access.discover',
      publishedDiscoveryEvent(),
    );
  });

  it('reruns a finished cycle that still has pending delegates', async () => {
    persistentCacheService.get.mockResolvedValue(
      discoveryState({
        state: 'ready',
        cycleStartedAt: CYCLE_STARTED_AT.getTime(),
        lastProgressRegisteredAt: CYCLE_STARTED_AT.getTime(),
      }),
    );
    discoverCommand.hasPendingDelegates.mockResolvedValue(true);

    await service.runRecovery();

    expect(discoverCommand.hasPendingDelegates).toHaveBeenCalledWith(CYCLE_STARTED_AT);
    expect(amqp.publish).toHaveBeenCalledWith(
      expect.any(String),
      'unique.outlook-semantic-mcp.delegated-access.discover',
      publishedDiscoveryEvent(),
    );
  });

  it('leaves a finished cycle without pending delegates alone', async () => {
    persistentCacheService.get.mockResolvedValue(
      discoveryState({
        state: 'ready',
        cycleStartedAt: CYCLE_STARTED_AT.getTime(),
        lastProgressRegisteredAt: CYCLE_STARTED_AT.getTime(),
      }),
    );

    await service.runRecovery();

    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('leaves a discovery that is making progress alone', async () => {
    persistentCacheService.get.mockResolvedValue(
      discoveryState({
        state: 'running',
        cycleStartedAt: CYCLE_STARTED_AT.getTime(),
        lastProgressRegisteredAt: NOW.getTime() - 60_000,
      }),
    );

    await service.runRecovery();

    expect(discoverCommand.hasPendingDelegates).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('does nothing before the first discovery has run', async () => {
    persistentCacheService.get.mockResolvedValue(null);

    await service.runRecovery();

    expect(amqp.publish).not.toHaveBeenCalled();
  });
});
