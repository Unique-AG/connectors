import { SchedulerRegistry } from '@nestjs/schedule';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { type AppConfig, loadFeaturesConfig } from '~/config';
import { DirectorySyncSchedulerService } from '../directories-sync-scheduler.service';
import type { SyncDirectoriesForAllUserProfilesCommand } from '../sync-directories-for-all-user-profiles.command';

const schedulerFor = (directorySyncMode: string) => {
  const registry = new SchedulerRegistry();
  const syncAllUsers = { run: vi.fn().mockResolvedValue(undefined) };
  const service = new DirectorySyncSchedulerService(
    registry,
    syncAllUsers as unknown as SyncDirectoriesForAllUserProfilesCommand,
    { directorySyncCronSchedule: '*/5 * * * *' } as AppConfig,
    loadFeaturesConfig({
      MCP_BACKEND: 'microsoft_graph',
      MCP_TOOLS: JSON.stringify(['search_emails']),
      DELEGATED_ACCESS_SCAN: 'disabled',
      DIRECTORY_SYNC_MODE: directorySyncMode,
    }),
  );
  return { registry, syncAllUsers, service };
};

describe('DirectorySyncSchedulerService', () => {
  let stop: (() => void) | undefined;

  afterEach(() => {
    stop?.();
    stop = undefined;
  });

  it('registers no cron job and runs no scan at startup in on_demand mode', () => {
    const { registry, syncAllUsers, service } = schedulerFor('on_demand');

    service.onModuleInit();

    expect([...registry.getCronJobs().keys()]).toEqual([]);
    expect(syncAllUsers.run).not.toHaveBeenCalled();
  });

  it('scans at startup and registers the cron job in scheduled mode', () => {
    const { registry, syncAllUsers, service } = schedulerFor('scheduled');
    stop = () => service.onModuleDestroy();

    service.onModuleInit();

    expect([...registry.getCronJobs().keys()]).toEqual(['sharepoint-scan']);
    expect(syncAllUsers.run).toHaveBeenCalled();
  });
});
