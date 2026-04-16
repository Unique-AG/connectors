import type { SiteSyncStep } from '../constants/sync-step.enum';

export class PermissionsSyncError extends Error {
  public constructor(
    public readonly step: SiteSyncStep,
    cause: unknown,
  ) {
    super(`Permissions sync failed at step: ${step}`, { cause });
  }
}
