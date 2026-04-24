/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DeleteInboxRecoveryService } from '../delete-inbox-recovery.service';

const makeService = (deps: { db?: any; amqp?: any; schedulerRegistry?: any }) => {
  const schedulerRegistry = deps.schedulerRegistry ?? {
    addCronJob: vi.fn(),
    getCronJob: vi.fn().mockReturnValue({ stop: vi.fn() }),
  };
  const amqp = deps.amqp ?? { publish: vi.fn().mockResolvedValue(true) };
  const db = deps.db ?? { select: vi.fn() };

  const service = new DeleteInboxRecoveryService(schedulerRegistry, amqp, db);
  // Prevent the real cron job from being registered during tests
  vi.spyOn(service as any, 'setupCronJob').mockImplementation(() => {});
  service.onModuleInit();

  return { service, amqp, db, schedulerRegistry };
};

const makeSelectChain = (result: any[]) => {
  const mockWhere = vi.fn().mockResolvedValue(result);
  const mockFrom = vi.fn().mockReturnValue({ where: mockWhere });
  const mockSelect = vi.fn().mockReturnValue({ from: mockFrom });
  return { mockSelect, mockFrom, mockWhere };
};

describe('DeleteInboxRecoveryService.checkAndRetriggerStuckDeletions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('publishes retrigger event for each stuck deletion', async () => {
    const configs = [
      { userProfileId: 'user_profile_01jxk5r1s2fq9att23mp4z5ef2' },
      { userProfileId: 'user_profile_01jxk5r1s2fq9att23mp4z5ef3' },
    ];
    const { mockSelect } = makeSelectChain(configs);
    const amqp = { publish: vi.fn().mockResolvedValue(true) };
    const db = { select: mockSelect };

    const { service } = makeService({ db, amqp });

    await service.checkAndRetriggerStuckDeletions();

    expect(amqp.publish).toHaveBeenCalledTimes(2);
    for (const call of amqp.publish.mock.calls) {
      expect(call[0]).toBe(MAIN_EXCHANGE.name);
      expect(call[1]).toBe('unique.outlook-semantic-mcp.delete-inbox-data.execute');
    }
  });

  it('does nothing when no stuck deletions found', async () => {
    const { mockSelect } = makeSelectChain([]);
    const amqp = { publish: vi.fn().mockResolvedValue(true) };
    const db = { select: mockSelect };

    const { service } = makeService({ db, amqp });

    await service.checkAndRetriggerStuckDeletions();

    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('skips when shutting down', async () => {
    const { mockSelect } = makeSelectChain([
      { userProfileId: 'user_profile_01jxk5r1s2fq9att23mp4z5ef2' },
    ]);
    const amqp = { publish: vi.fn().mockResolvedValue(true) };
    const db = { select: mockSelect };

    const { service } = makeService({ db, amqp });
    (service as any).isShuttingDown = true;

    await service.checkAndRetriggerStuckDeletions();

    expect(amqp.publish).not.toHaveBeenCalled();
  });
});
