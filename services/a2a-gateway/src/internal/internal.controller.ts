import {
  BadRequestException,
  Body,
  Controller,
  Get,
  HttpCode,
  HttpStatus,
  Param,
  Post,
  Req,
  UseGuards,
} from '@nestjs/common';
import type { Request } from 'express';
import { z } from 'zod';
import { ClusterIdentityGuard, requestIdentity } from '../auth/identity.guard.js';
import { ConnectionService } from '../credentials/connection.service.js';
import { InternalService } from './internal.service.js';

const bindRequest = z.object({ assistantId: z.string().min(1).max(200) }).strict();

const reconcileRequest = z.object({
  assistantId: z.string().min(1),
  executionProvider: z.enum(['NATIVE', 'A2A']).optional(),
  deleted: z.boolean().default(false),
});

@Controller('internal')
@UseGuards(ClusterIdentityGuard)
export class InternalController {
  public constructor(
    private readonly internal: InternalService,
    private readonly connections: ConnectionService,
  ) {}

  @Get('capabilities')
  public capabilities() {
    return {
      version: '0.0.0',
      protocolVersions: ['1.0'],
      features: {
        inbound: true,
        outbound: true,
      },
    } as const;
  }

  @Get('connections/:connectionId')
  public connection(@Req() request: Request, @Param('connectionId') connectionId: string) {
    return this.connections.internalSummary(requestIdentity(request), connectionId);
  }

  @Post('connections/:connectionId/bind')
  @HttpCode(HttpStatus.OK)
  public bind(
    @Req() request: Request,
    @Param('connectionId') connectionId: string,
    @Body() body: unknown,
  ) {
    const parsed = bindRequest.safeParse(body);
    if (!parsed.success) {
      throw new BadRequestException('invalid bind request');
    }
    return this.connections.bind(requestIdentity(request), connectionId, parsed.data.assistantId);
  }

  @Post('publications/reconcile')
  public async reconcilePublication(@Req() request: Request, @Body() body: unknown): Promise<void> {
    const parsed = reconcileRequest.safeParse(body);
    if (!parsed.success) {
      throw new BadRequestException('invalid publication reconciliation request');
    }
    const identity = requestIdentity(request);
    await this.internal.reconcilePublication(identity, parsed.data);
  }
}
