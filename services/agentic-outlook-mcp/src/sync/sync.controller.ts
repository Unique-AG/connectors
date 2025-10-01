import { TokenValidationResult } from '@unique-ag/mcp-oauth';
import { Controller, Post, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiResponse, ApiTags } from '@nestjs/swagger';
import { TypeID } from 'typeid-js';
import { JwtGuard } from '../jwt.guard';
import { User } from '../user.decorator';
import { SyncStatusDto } from './dto/sync-status.dto';
import { SyncService } from './sync.service';

@ApiTags('sync')
@ApiBearerAuth()
@Controller('sync')
@UseGuards(JwtGuard)
export class SyncController {
  public constructor(private readonly syncService: SyncService) {}

  @Post()
  @ApiOperation({ summary: 'Enable sync for the authenticated user' })
  @ApiResponse({ status: 201, description: 'Sync enabled successfully', type: SyncStatusDto })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  public async createSyncJob(@User() user: TokenValidationResult): Promise<SyncStatusDto> {
    return this.syncService.enableSync(TypeID.fromString(user.userProfileId, 'user_profile'));
  }

  // @Delete(':syncJobId')
  // public async deleteSyncJob(
  //   @Param('userProfileId') userProfileId: string,
  //   @Param('syncJobId') syncJobId: string,
  // ) {
  //   return this.syncService.deleteSyncJob(userProfileId, syncJobId);
  // }

  // @Post(':syncJobId/run')
  // public async runSyncJob(
  //   @Param('userProfileId') userProfileId: string,
  //   @Param('syncJobId') syncJobId: string,
  // ) {
  //   return this.syncService.runSyncJob(userProfileId, syncJobId);
  // }
}
