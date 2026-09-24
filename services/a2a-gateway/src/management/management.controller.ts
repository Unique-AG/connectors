import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  Get,
  Headers,
  Param,
  Put,
  Req,
  UseGuards,
} from '@nestjs/common';
import type { Request } from 'express';
import { KongIdentityGuard, requestIdentity } from '../auth/identity.guard.js';
import { ManagementService } from './management.service.js';
import { publicationWriteSchema } from './publication-configuration.js';

@Controller('management')
@UseGuards(KongIdentityGuard)
export class ManagementController {
  public constructor(private readonly management: ManagementService) {}

  @Get('publications/:assistantId')
  public async getPublication(@Req() request: Request, @Param('assistantId') assistantId: string) {
    const identity = requestIdentity(request);
    return this.management.getPublication(identity, assistantId);
  }

  @Put('publications/:assistantId')
  public async putPublication(
    @Req() request: Request,
    @Param('assistantId') assistantId: string,
    @Headers('if-match') ifMatch: string | undefined,
    @Body() body: unknown,
  ) {
    const identity = requestIdentity(request);
    const parsedInput = publicationWriteSchema.safeParse(body);
    if (!parsedInput.success) {
      throw new BadRequestException('invalid publication configuration');
    }
    const input = parsedInput.data;
    const expectedVersion = ifMatch === undefined ? undefined : Number(ifMatch.replaceAll('"', ''));
    if (
      ifMatch !== undefined &&
      (!/^(?:[1-9]\d*|"[1-9]\d*")$/.test(ifMatch) || !Number.isSafeInteger(expectedVersion))
    ) {
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
    await this.management.disablePublication(identity, assistantId);
  }
}
