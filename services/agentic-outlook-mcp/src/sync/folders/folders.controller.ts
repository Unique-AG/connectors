import { Controller, Get, Param, Patch } from '@nestjs/common';
import { TypeID } from 'typeid-js';
import { FoldersService } from './folders.service';

@Controller('users/:userProfileId/sync-jobs/:syncJobId/folders')
export class FoldersController {
  public constructor(private readonly foldersService: FoldersService) {}

  @Get()
  public async getFolders(
    @Param('userProfileId') userProfileId: string,
    @Param('syncJobId') syncJobId: string,
  ) {
    return this.foldersService.getFolders(
      TypeID.fromString(userProfileId, 'user_profile'),
      TypeID.fromString(syncJobId, 'sync_job'),
    );
  }

  @Patch()
  public async updateFolders(
    @Param('userProfileId') userProfileId: string,
    @Param('syncJobId') syncJobId: string,
  ) {
    return this.foldersService.syncFolders(
      TypeID.fromString(userProfileId, 'user_profile'),
      TypeID.fromString(syncJobId, 'sync_job'),
    );
  }
}
