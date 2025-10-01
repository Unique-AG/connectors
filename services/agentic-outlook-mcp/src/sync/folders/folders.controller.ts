import { TokenValidationResult } from '@unique-ag/mcp-oauth';
import { Controller, Get, Patch, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiResponse, ApiTags } from '@nestjs/swagger';
import { TypeID } from 'typeid-js';
import { JwtGuard } from '../../jwt.guard';
import { User } from '../../user.decorator';
import { FolderArrayDto } from '../dto/folder.dto';
import { FoldersService } from './folders.service';

@ApiTags('folders')
@ApiBearerAuth()
@Controller('sync/folders')
@UseGuards(JwtGuard)
export class FoldersController {
  public constructor(private readonly foldersService: FoldersService) {}

  @Get()
  @ApiOperation({ summary: 'Get all folders for the authenticated user' })
  @ApiResponse({ status: 200, description: 'List of folders', type: FolderArrayDto })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  public async getFolders(@User() user: TokenValidationResult): Promise<FolderArrayDto> {
    return this.foldersService.getFolders(TypeID.fromString(user.userProfileId, 'user_profile'));
  }

  @Patch()
  @ApiOperation({ summary: 'Sync folders from Microsoft Graph for the authenticated user' })
  @ApiResponse({ status: 200, description: 'Folders synced successfully' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  public async updateFolders(@User() user: TokenValidationResult): Promise<void> {
    return this.foldersService.syncFolders(TypeID.fromString(user.userProfileId, 'user_profile'));
  }
}
