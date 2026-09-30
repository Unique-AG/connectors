import {
  BadRequestException,
  Body,
  Controller,
  HttpCode,
  HttpStatus,
  Post,
  Req,
  UseGuards,
} from '@nestjs/common';
import type { Request } from 'express';
import { ClusterIdentityGuard, requestIdentity } from '../auth/identity.guard.js';
import { executionRequest, OutboundExecutionService } from './outbound-execution.service.js';

@Controller('internal/executions')
@UseGuards(ClusterIdentityGuard)
export class OutboundController {
  public constructor(private readonly executions: OutboundExecutionService) {}

  @Post()
  @HttpCode(HttpStatus.ACCEPTED)
  public start(@Req() request: Request, @Body() body: unknown) {
    const parsed = executionRequest.safeParse(body);
    if (!parsed.success) {
      throw new BadRequestException('invalid execution request');
    }
    return this.executions.start(requestIdentity(request), parsed.data);
  }
}
