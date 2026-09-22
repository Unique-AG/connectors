import { BadRequestException, Body, Controller, Get, Post, Req, UseGuards } from '@nestjs/common';
import type { Request } from 'express';
import { z } from 'zod';
import { ClusterIdentityGuard, requestIdentity } from '../auth/identity.guard.js';
import { InternalService } from './internal.service.js';

const reconcileRequest = z.object({
  assistantId: z.string().min(1),
  executionProvider: z.enum(['NATIVE', 'A2A']).optional(),
  deleted: z.boolean().default(false),
});

@Controller('internal')
@UseGuards(ClusterIdentityGuard)
export class InternalController {
  public constructor(private readonly internal: InternalService) {}

  @Get('capabilities')
  public capabilities() {
    return {
      version: '0.0.0',
      protocolVersions: ['1.0'],
      features: {
        inbound: false,
        outbound: false,
      },
    } as const;
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
