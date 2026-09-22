import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  ForbiddenException,
  Get,
  Headers,
  Param,
  Put,
  Req,
  UseGuards,
} from '@nestjs/common';
import type { Request } from 'express';
import { z } from 'zod';
import { KongIdentityGuard, requestIdentity } from '../auth/identity.guard.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { ManagementService } from './management.service.js';

const publicationWrite = z.object({
  enabled: z.boolean(),
  card: z.record(z.string(), z.unknown()).default({}),
  skills: z.array(z.unknown()).default([]),
});

function canWrite(value: unknown): boolean {
  return typeof value === 'object' && value !== null && Reflect.get(value, 'canWrite') === true;
}

@Controller('management')
@UseGuards(KongIdentityGuard)
export class ManagementController {
  public constructor(
    private readonly management: ManagementService,
    private readonly unique: UniqueInternalClient,
  ) {}

  @Get('publications/:assistantId')
  public async getPublication(@Req() request: Request, @Param('assistantId') assistantId: string) {
    const identity = requestIdentity(request);
    await this.unique.getAssistant(identity, assistantId);
    return this.management.getPublication(identity.companyId, assistantId);
  }

  @Put('publications/:assistantId')
  public async putPublication(
    @Req() request: Request,
    @Param('assistantId') assistantId: string,
    @Headers('if-match') ifMatch: string | undefined,
    @Body() body: unknown,
  ) {
    const identity = requestIdentity(request);
    const access = await this.unique.verifySpaceManagement(identity, assistantId);
    if (!canWrite(access)) {
      throw new ForbiddenException('space management access required');
    }
    const parsedInput = publicationWrite.safeParse(body);
    if (!parsedInput.success) {
      throw new BadRequestException('invalid publication configuration');
    }
    const input = parsedInput.data;
    const expectedVersion = ifMatch === undefined ? undefined : Number(ifMatch.replaceAll('"', ''));
    if (ifMatch !== undefined && !Number.isSafeInteger(expectedVersion)) {
      throw new BadRequestException('If-Match must contain a numeric publication version');
    }
    return this.management.putPublication(identity, assistantId, input, expectedVersion);
  }

  @Delete('publications/:assistantId')
  public async deletePublication(
    @Req() request: Request,
    @Param('assistantId') assistantId: string,
  ): Promise<void> {
    const identity = requestIdentity(request);
    const access = await this.unique.verifySpaceManagement(identity, assistantId);
    if (!canWrite(access)) {
      throw new ForbiddenException('space management access required');
    }
    await this.management.disablePublication(identity.companyId, assistantId);
  }
}
