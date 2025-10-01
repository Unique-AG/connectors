import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, emails, folders, userProfiles } from '../drizzle';
import { FoldersService } from './folders/folders.service';

@Injectable()
export class SyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly foldersService: FoldersService,
  ) {}

  public async enableSync(userProfileId: TypeID<'user_profile'>) {
    this.logger.log({ msg: 'Enabling sync', userProfileId });
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

  public async syncFolders(userProfileId: TypeID<'user_profile'>) {
    this.logger.log({ msg: 'Syncing folders', userProfileId });
    await this.foldersService.syncFolders(userProfileId);
  }

  public async deactivateSync(userProfileId: TypeID<'user_profile'>, wipeData: boolean) {
    this.logger.log({ msg: 'Deactivating sync', userProfileId, wipeData });
    await this.db
      .update(userProfiles)
      .set({ syncDeactivatedAt: new Date() })
      .where(eq(userProfiles.id, userProfileId.toString()));

    if (wipeData) await this.wipeAllUserData(userProfileId);
  }

  public async wipeAllUserData(userProfileId: TypeID<'user_profile'>) {
    this.logger.log({ msg: 'Wiping all user data', userProfileId });
    await Promise.all([
      this.db.delete(folders).where(eq(folders.userProfileId, userProfileId.toString())),
      this.db.delete(emails).where(eq(emails.userProfileId, userProfileId.toString())),
    ]);
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
