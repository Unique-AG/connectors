import { TokenValidationResult } from '@unique-ag/mcp-oauth';
import { Controller, Delete, Get, Param, Post, UseGuards } from '@nestjs/common';
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

  @Post(':folderId')
  @ApiOperation({ summary: 'Activate sync for a folder.' })
  @ApiResponse({ status: 200, description: 'Folder sync activated successfully' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  public async updateFolders(
    @User() user: TokenValidationResult,
    @Param('folderId') folderId: string,
  ): Promise<void> {
    return this.foldersService.activateSync(
      TypeID.fromString(user.userProfileId, 'user_profile'),
      folderId,
    );
  }

  @Delete(':folderId')
  @ApiOperation({ summary: 'Deactivate sync for a folder.' })
  @ApiResponse({ status: 200, description: 'Folder sync deactivated successfully' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  public async deactivateSync(
    @User() user: TokenValidationResult,
    @Param('folderId') folderId: string,
  ): Promise<void> {
    return this.foldersService.deactivateSync(
      TypeID.fromString(user.userProfileId, 'user_profile'),
      folderId,
    );
  }
}
