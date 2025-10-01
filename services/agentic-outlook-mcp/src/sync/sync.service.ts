import { Inject, Injectable, Logger, OnApplicationBootstrap } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, userProfiles } from '../drizzle';
import { GraphClientFactory } from '../msgraph/graph-client.factory';
import { FoldersService } from './folders/folders.service';

@Injectable()
export class SyncService implements OnApplicationBootstrap {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly foldersService: FoldersService,
  ) {}

  public async onApplicationBootstrap() {
    // await this.startSyncRun();
  }

  public async enableSync(userProfileId: TypeID<'user_profile'>) {
    await this.db
      .update(userProfiles)
      .set({ syncActivatedAt: new Date() })
      .where(eq(userProfiles.id, userProfileId.toString()));
    await this.foldersService.syncFolders(userProfileId);
    
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId.toString()),
      columns: {
        syncActivatedAt: true,
        syncDeactivatedAt: true,
        syncLastSyncedAt: true,
      },
    });
    if (!userProfile) throw new Error('User profile not found');
    
    return {
      syncActivatedAt: userProfile.syncActivatedAt?.toISOString() ?? null,
      syncDeactivatedAt: userProfile.syncDeactivatedAt?.toISOString() ?? null,
      syncLastSyncedAt: userProfile.syncLastSyncedAt?.toISOString() ?? null,
    };
  }

  // @Cron('0 */30 * * * *') // Every 30 minutes
  // public async startSyncRun() {
  //   this.logger.log({ msg: 'Starting sync run' });

  //   const syncJobs = await this.db.query.syncJobs.findMany();

  //   const results = await Promise.allSettled(
  //     syncJobs.map((syncJob) =>
  //       new SyncJob(
  //         syncJob,
  //         this.graphClientFactory.createClientForUser(syncJob.userProfileId),
  //       ).run(),
  //     ),
  //   );

  //   this.logger.log({ msg: 'Sync run completed', results });
  // }

  // public async createSyncJob(userProfileId: TypeID<'user_profile'>) {
  //   const syncJob = await this.db
  //     .insert(syncJobs)
  //     .values({ userProfileId: userProfileId.toString() })
  //     .returning();
  //   if (!syncJob[0]) throw new Error('Failed to create sync job');
  //   await this.foldersService.syncFolders(
  //     userProfileId,
  //     TypeID.fromString(syncJob[0].id, 'sync_job'),
  //   );
  //   return syncJob;
  // }

  // public async deleteSyncJob(userProfileId: string, syncJobId: string) {
  //   return this.db
  //     .update(syncJobs)
  //     .set({ deactivatedAt: new Date() })
  //     .where(and(eq(syncJobs.id, syncJobId), eq(syncJobs.userProfileId, userProfileId)));
  // }

  // public async runSyncJob(userProfileId: TypeID<'user_profile'>, syncJobId: string) {
  //   this.logger.log({ msg: 'Manually run individual sync job', userProfileId, syncJobId });
  //   const syncJob = await this.db.query.syncJobs.findFirst({
  //     where: and(eq(syncJobs.id, syncJobId), eq(syncJobs.userProfileId, userProfileId)),
  //   });

  //   if (!syncJob) throw new NotFoundException('Sync job not found');
  //   const job = new SyncJob(syncJob, this.graphClientFactory.createClientForUser(userProfileId));
  //   await job.run();
  // }
}
