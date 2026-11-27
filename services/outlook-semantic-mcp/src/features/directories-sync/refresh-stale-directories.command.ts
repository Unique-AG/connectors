import { isUpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DirectorySyncMode, type FeaturesConfig, featuresConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, directoriesSync } from '~/db';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { SyncDirectoriesCommand } from './sync-directories.command';

export const ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS = 4 * 60 * 60 * 1000;
export const ON_DEMAND_DIRECTORY_SYNC_RETRY_AFTER_MS = 5 * 60 * 1000;

// With DIRECTORY_SYNC_MODE=on_demand no job keeps the folder cache fresh, so a tool that reads
// it refreshes the caller's folders first once they are older than the max age. Concurrent calls
// share one refresh. A failed refresh leaves the cached folders in use and is not retried for a
// while, so a throttled or failing Graph is not hit again before every search; only a revoked
// sign-in is passed on, so the client asks the user to sign in again.
@Injectable()
export class RefreshStaleDirectoriesCommand {
  private readonly logger = new Logger(this.constructor.name);
  private readonly inFlight = new Map<string, Promise<void>>();
  private readonly lastFailureAt = new Map<string, number>();

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    @Inject(featuresConfig.KEY) private readonly features: FeaturesConfig,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<void> {
    if (this.features.directorySyncMode !== DirectorySyncMode.OnDemand) {
      return;
    }
    const key = userProfileId.toString();
    const running = this.inFlight.get(key);
    if (running) {
      return running;
    }
    const refresh = this.refreshIfStale(userProfileId).finally(() => this.inFlight.delete(key));
    this.inFlight.set(key, refresh);
    return refresh;
  }

  private async refreshIfStale(userProfileId: UserProfileTypeID): Promise<void> {
    const key = userProfileId.toString();
    const failedAt = this.lastFailureAt.get(key);
    if (failedAt !== undefined && Date.now() - failedAt < ON_DEMAND_DIRECTORY_SYNC_RETRY_AFTER_MS) {
      return;
    }
    const stats = await this.db.query.directoriesSync.findFirst({
      columns: { lastDeltaSyncRanAt: true },
      where: eq(directoriesSync.userProfileId, key),
    });
    const lastSyncAt = stats?.lastDeltaSyncRanAt;
    if (lastSyncAt && Date.now() - lastSyncAt.getTime() < ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS) {
      return;
    }

    this.logger.log({
      userProfileId: key,
      lastSyncAt: lastSyncAt?.toISOString() ?? null,
      msg: 'Folder cache is stale, syncing directories before reading it',
    });
    try {
      await this.syncDirectoriesCommand.run(userProfileId, { allowDelegateFallback: false });
      this.lastFailureAt.delete(key);
    } catch (err) {
      if (isUpstreamCredentialRevokedError(err)) {
        throw err;
      }
      this.lastFailureAt.set(key, Date.now());
      this.logger.warn({
        userProfileId: key,
        err,
        msg: 'Folder sync failed, reading the cached folders',
      });
    }
  }
}
