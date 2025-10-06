import { TokenValidationResult } from '@unique-ag/mcp-oauth';
import { Controller, Delete, Patch, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiResponse, ApiTags } from '@nestjs/swagger';
import { TypeID } from 'typeid-js';
import { JwtGuard } from '../jwt.guard';
import { User } from '../user.decorator';
import { SyncService } from './sync.service';

@ApiTags('sync')
@ApiBearerAuth()
@Controller('sync')
@UseGuards(JwtGuard)
export class SyncController {
  public constructor(private readonly syncService: SyncService) {}

  @Patch()
  @ApiOperation({ summary: 'Sync folders for the authenticated user' })
  @ApiResponse({ status: 200, description: 'Folders synced successfully' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  public async syncFolders(@User() user: TokenValidationResult): Promise<void> {
    return this.syncService.syncFolders(TypeID.fromString(user.userProfileId, 'user_profile'));
  }

  @Delete()
  @ApiOperation({ summary: 'Delete all user data for the authenticated user' })
  @ApiResponse({ status: 200, description: 'User data deleted successfully' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  public async deleteAllUserData(@User() user: TokenValidationResult): Promise<void> {
    return this.syncService.deleteAllUserData(
      TypeID.fromString(user.userProfileId, 'user_profile'),
    );
  }
}
