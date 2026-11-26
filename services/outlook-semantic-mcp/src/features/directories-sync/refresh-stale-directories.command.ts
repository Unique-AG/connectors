import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DirectorySyncMode, type FeaturesConfig, featuresConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, directoriesSync } from '~/db';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { SyncDirectoriesCommand } from './sync-directories.command';

export const ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS = 4 * 60 * 60 * 1000;

// With DIRECTORY_SYNC_MODE=on_demand no job keeps the folder cache fresh, so a tool that reads
// it refreshes the caller's folders first once they are older than the max age.
@Injectable()
export class RefreshStaleDirectoriesCommand {
  private readonly logger = new Logger(this.constructor.name);

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
    const stats = await this.db.query.directoriesSync.findFirst({
      columns: { lastDeltaSyncRanAt: true },
      where: eq(directoriesSync.userProfileId, userProfileId.toString()),
    });
    const lastSyncAt = stats?.lastDeltaSyncRanAt;
    if (lastSyncAt && Date.now() - lastSyncAt.getTime() < ON_DEMAND_DIRECTORY_SYNC_MAX_AGE_MS) {
      return;
    }

    this.logger.log({
      userProfileId: userProfileId.toString(),
      lastSyncAt: lastSyncAt?.toISOString() ?? null,
      msg: 'Folder cache is stale, syncing directories before reading it',
    });
    await this.syncDirectoriesCommand.run(userProfileId, { allowDelegateFallback: false });
  }
}
