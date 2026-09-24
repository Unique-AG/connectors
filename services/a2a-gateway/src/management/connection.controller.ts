import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  Get,
  Headers,
  Param,
  Post,
  Put,
  Req,
  UseGuards,
} from '@nestjs/common';
import type { Request } from 'express';
import { KongIdentityGuard, requestIdentity } from '../auth/identity.guard.js';
import { ConnectionService } from '../credentials/connection.service.js';
import { connectionWrite } from '../credentials/credential-profile.js';

function configuration(body: unknown) {
  const result = connectionWrite.safeParse(body);
  if (!result.success) {
    throw new BadRequestException('invalid connection configuration');
  }
  return result.data;
}
function version(value: string | undefined): number {
  if (!value || !/^(?:[1-9]\d*|"[1-9]\d*")$/.test(value)) {
    throw new BadRequestException('If-Match must contain a positive connection version');
  }
  const parsed = Number(value.replaceAll('"', ''));
  if (!Number.isSafeInteger(parsed)) {
    throw new BadRequestException('invalid connection version');
  }
  return parsed;
}

@Controller('management/connections')
@UseGuards(KongIdentityGuard)
export class ConnectionController {
  public constructor(private readonly connections: ConnectionService) {}

  @Get()
  public list(@Req() request: Request) {
    return this.connections.list(requestIdentity(request));
  }

  @Get(':connectionId')
  public get(@Req() request: Request, @Param('connectionId') connectionId: string) {
    return this.connections.get(requestIdentity(request), connectionId);
  }

  @Post()
  public create(@Req() request: Request, @Body() body: unknown) {
    return this.connections.save(requestIdentity(request), configuration(body));
  }

  @Put(':connectionId')
  public replace(
    @Req() request: Request,
    @Param('connectionId') connectionId: string,
    @Headers('if-match') ifMatch: string | undefined,
    @Body() body: unknown,
  ) {
    return this.connections.save(requestIdentity(request), configuration(body), {
      id: connectionId,
      version: version(ifMatch),
    });
  }

  @Delete(':connectionId/credentials')
  public revoke(
    @Req() request: Request,
    @Param('connectionId') connectionId: string,
    @Headers('if-match') ifMatch: string | undefined,
  ): Promise<void> {
    return this.connections.revoke(requestIdentity(request), connectionId, version(ifMatch));
  }
}
