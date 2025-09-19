import { Controller, Delete, Param, Post } from '@nestjs/common';
import { TypeID } from 'typeid-js';
import { SyncService } from './sync.service';

@Controller('users/:userProfileId/sync-jobs')
export class SyncController {
  public constructor(private readonly syncService: SyncService) {}

  @Post()
  public async createSyncJob(@Param('userProfileId') userProfileId: string) {
    return this.syncService.createSyncJob(TypeID.fromString(userProfileId, 'user_profile'));
  }

  @Delete(':syncJobId')
  public async deleteSyncJob(
    @Param('userProfileId') userProfileId: string,
    @Param('syncJobId') syncJobId: string,
  ) {
    return this.syncService.deleteSyncJob(userProfileId, syncJobId);
  }

  // @Post(':syncJobId/run')
  // public async runSyncJob(
  //   @Param('userProfileId') userProfileId: string,
  //   @Param('syncJobId') syncJobId: string,
  // ) {
  //   return this.syncService.runSyncJob(userProfileId, syncJobId);
  // }
}
