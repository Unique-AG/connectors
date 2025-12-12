import { TokenValidationResult } from '@unique-ag/mcp-oauth';
import { Body, Controller, HttpCode, HttpStatus, Post, UseGuards } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiResponse, ApiTags } from '@nestjs/swagger';
import { TypeID } from 'typeid-js';
import { JwtGuard } from '../jwt.guard';
import { User } from '../user.decorator';
import { BatchDto } from './batch.dto';
import { BatchService } from './batch.service';

@ApiTags('batch')
@ApiBearerAuth()
@Controller('batch')
@UseGuards(JwtGuard)
export class BatchController {
  public constructor(private readonly batchService: BatchService) {}

  @Post()
  @ApiOperation({ summary: 'Batch process Powersync write operations for the authenticated user' })
  @ApiResponse({ status: 200, description: 'Batch processed successfully' })
  @ApiResponse({ status: 401, description: 'Unauthorized' })
  @HttpCode(HttpStatus.OK)
  public async batch(@User() user: TokenValidationResult, @Body() body: BatchDto) {
    await this.batchService.batch(TypeID.fromString(user.userProfileId, 'user_profile'), body);
    return { success: true, message: 'Batch processed successfully' };
  }
}
