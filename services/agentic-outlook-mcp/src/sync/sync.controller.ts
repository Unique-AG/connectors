import { TokenValidationResult } from '@unique-ag/mcp-oauth';
import { Body, Controller, Delete, Patch, Post, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiResponse, ApiTags } from '@nestjs/swagger';
import { TypeID } from 'typeid-js';
import { JwtGuard } from '../jwt.guard';
import { User } from '../user.decorator';
import { DeleteSyncDto } from './dto/delete-sync.dto';
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
  public async activateSync(@User() user: TokenValidationResult): Promise<SyncStatusDto> {
    return this.syncService.enableSync(TypeID.fromString(user.userProfileId, 'user_profile'));
  }

  @Patch()
  @ApiOperation({ summary: 'Sync folders for the authenticated user' })
  @ApiResponse({ status: 200, description: 'Folders synced successfully' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  public async syncFolders(@User() user: TokenValidationResult): Promise<void> {
    return this.syncService.syncFolders(TypeID.fromString(user.userProfileId, 'user_profile'));
  }

  @Delete()
  @ApiOperation({ summary: 'Deactivate sync for the authenticated user' })
  @ApiResponse({ status: 200, description: 'Sync deactivated successfully' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  public async deactivateSync(@User() user: TokenValidationResult, @Body() body: DeleteSyncDto) {
    return this.syncService.deactivateSync(
      TypeID.fromString(user.userProfileId, 'user_profile'),
      body.wipeData ?? false,
    );
  }
}
