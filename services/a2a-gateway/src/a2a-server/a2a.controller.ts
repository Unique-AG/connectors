import { formatSSEEvent } from '@a2a-js/sdk';
import {
  Body,
  Controller,
  Get,
  Headers,
  HttpCode,
  HttpStatus,
  Param,
  Post,
  Req,
  Res,
  UseGuards,
} from '@nestjs/common';
import type { Request, Response } from 'express';
import { KongIdentityGuard, requestIdentity } from '../auth/identity.guard.js';
import { A2aSdkService } from './a2a-sdk.service.js';
import { PublicationService } from './publication.service.js';

function isAsyncIterable(value: unknown): value is AsyncIterable<unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    Symbol.asyncIterator in value &&
    typeof Reflect.get(value, Symbol.asyncIterator) === 'function'
  );
}

@Controller('a2a/agents')
export class A2aController {
  public constructor(
    private readonly a2a: A2aSdkService,
    private readonly publications: PublicationService,
  ) {}

  @Get(':publicationId/.well-known/agent-card.json')
  public async agentCard(
    @Param('publicationId') publicationId: string,
    @Headers('if-none-match') ifNoneMatch: string | undefined,
    @Res() response: Response,
  ): Promise<void> {
    const card = await this.publications.getAgentCard(publicationId);
    const etag = `"${publicationId}-${card.version}"`;
    response.setHeader('Cache-Control', 'public, max-age=60, must-revalidate');
    response.setHeader('ETag', etag);
    if (ifNoneMatch === etag) {
      response.status(HttpStatus.NOT_MODIFIED).end();
      return;
    }
    response.json(card);
  }

  @Get()
  @UseGuards(KongIdentityGuard)
  public async catalog(@Req() request: Request) {
    return { agents: await this.publications.catalog(requestIdentity(request)) };
  }

  @Post(':publicationId')
  @UseGuards(KongIdentityGuard)
  @HttpCode(HttpStatus.OK)
  public async jsonRpc(
    @Param('publicationId') publicationId: string,
    @Headers('a2a-version') requestedVersion: string | undefined,
    @Body() body: unknown,
    @Req() request: Request,
    @Res() response: Response,
  ): Promise<void> {
    const result = await this.a2a.handleJsonRpc({
      body,
      headers: request.headers,
      identity: requestIdentity(request),
      publicationId,
      requestedVersion,
    });
    response.setHeader('A2A-Version', '1.0');
    if (!isAsyncIterable(result)) {
      response.json(result);
      return;
    }
    response.setHeader('Content-Type', 'text/event-stream');
    response.setHeader('Cache-Control', 'no-cache');
    response.setHeader('X-Accel-Buffering', 'no');
    for await (const event of result) {
      response.write(formatSSEEvent(event));
    }
    response.end();
  }
}
