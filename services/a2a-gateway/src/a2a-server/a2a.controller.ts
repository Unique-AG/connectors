import { formatSSEEvent } from '@a2a-js/sdk';
import { A2AError, toJsonRpcError } from '@a2a-js/sdk/errors';
import {
  Body,
  Controller,
  Get,
  Headers,
  HttpCode,
  HttpStatus,
  NotFoundException,
  Param,
  Post,
  Query,
  Req,
  Res,
  UseGuards,
} from '@nestjs/common';
import type { Request, Response } from 'express';
import { KongIdentityGuard, requestIdentity } from '../auth/identity.guard.js';
import { A2aSdkService } from './a2a-sdk.service.js';
import { InboundFilesService } from './inbound-files.service.js';
import { PublicationService } from './publication.service.js';

const KEEP_ALIVE_MS = 15_000;
const STREAMING_METHODS = new Set(['SendStreamingMessage', 'SubscribeToTask']);
// Per replica; bounds long-lived connections one user can hold open.
const MAX_STREAMS_PER_USER = 20;
const SUPPORTED_VERSION = /^1(\.0)?$/;

function jsonRpcId(body: unknown): string | number | null {
  const id = typeof body === 'object' && body !== null ? Reflect.get(body, 'id') : undefined;
  return typeof id === 'string' || typeof id === 'number' ? id : null;
}

function jsonRpcError(id: string | number | null, code: number, message: string) {
  return { jsonrpc: '2.0', id, error: { code, message } };
}

function isJsonRpcError(value: unknown): boolean {
  return typeof value === 'object' && value !== null && 'error' in value;
}

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
  private readonly streams = new Map<string, number>();

  public constructor(
    private readonly a2a: A2aSdkService,
    private readonly publications: PublicationService,
    private readonly files: InboundFilesService,
  ) {}

  @Get(':publicationId/.well-known/agent-card.json')
  public async agentCard(
    @Param('publicationId') publicationId: string,
    @Headers('if-none-match') ifNoneMatch: string | undefined,
    @Res() response: Response,
  ): Promise<void> {
    const { card, updatedAt } = await this.publications.getPublicAgentCard(publicationId);
    const etag = `"${publicationId}-${card.version}"`;
    response.setHeader('Cache-Control', 'public, max-age=60, must-revalidate');
    response.setHeader('ETag', etag);
    response.setHeader('Last-Modified', updatedAt.toUTCString());
    if (ifNoneMatch === etag) {
      response.status(HttpStatus.NOT_MODIFIED).end();
      return;
    }
    response.json(card);
  }

  @Get(':publicationId/files/:contentId')
  @UseGuards(KongIdentityGuard)
  public async file(
    @Param('publicationId') publicationId: string,
    @Param('contentId') contentId: string,
    @Query('taskId') taskId: string | undefined,
    @Req() request: Request,
    @Res() response: Response,
  ): Promise<void> {
    if (!taskId) {
      throw new NotFoundException('file not found');
    }
    const file = await this.files.download(
      requestIdentity(request),
      publicationId,
      taskId,
      contentId,
    );
    response.setHeader('Content-Type', file.mimeType);
    response.setHeader(
      'Content-Disposition',
      `attachment; filename*=UTF-8''${encodeURIComponent(file.filename)}`,
    );
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Content-Security-Policy', "sandbox; default-src 'none'");
    response.setHeader('Cache-Control', 'private, no-store');
    response.send(file.bytes);
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
    response.setHeader('A2A-Version', '1.0');
    const id = jsonRpcId(body);
    if (!request.is(['application/json', 'application/*+json'])) {
      response.json(jsonRpcError(id, -32005, 'Content-Type must be application/json'));
      return;
    }
    if (requestedVersion !== undefined && !SUPPORTED_VERSION.test(requestedVersion.trim())) {
      response.json(
        jsonRpcError(id, -32009, `A2A version ${requestedVersion} is not supported; use 1.0`),
      );
      return;
    }
    const identity = requestIdentity(request);
    const streamKey = `${identity.companyId}:${identity.userId}`;
    const method = typeof body === 'object' && body !== null ? Reflect.get(body, 'method') : '';
    const streaming = STREAMING_METHODS.has(String(method));
    const streams = this.streams.get(streamKey) ?? 0;
    if (streaming && streams >= MAX_STREAMS_PER_USER) {
      response
        .status(HttpStatus.TOO_MANY_REQUESTS)
        .json(jsonRpcError(id, -32603, 'too many concurrent streams'));
      return;
    }
    // The response (not the request) reports a client disconnect once the body has been read.
    const disconnected = new AbortController();
    if (streaming) {
      this.streams.set(streamKey, streams + 1);
    }
    response.on('close', () => {
      disconnected.abort();
      if (streaming) {
        const remaining = (this.streams.get(streamKey) ?? 1) - 1;
        if (remaining > 0) {
          this.streams.set(streamKey, remaining);
        } else {
          this.streams.delete(streamKey);
        }
      }
    });
    const result = await this.a2a.handleJsonRpc({
      body,
      headers: request.headers,
      identity,
      publicationId,
      requestedVersion,
      signal: disconnected.signal,
    });
    if (!isAsyncIterable(result)) {
      response.json(result);
      return;
    }
    // An error before the first event (e.g. unknown task) is a plain JSON-RPC error, not a stream.
    const events = result[Symbol.asyncIterator]();
    let first: IteratorResult<unknown>;
    try {
      first = await events.next();
    } catch (error) {
      if (!(error instanceof A2AError)) {
        throw error;
      }
      response.json({ jsonrpc: '2.0', id, error: toJsonRpcError(error) });
      return;
    }
    if (!first.done && isJsonRpcError(first.value)) {
      response.json(first.value);
      return;
    }
    response.setHeader('Content-Type', 'text/event-stream');
    response.setHeader('Cache-Control', 'no-cache');
    response.setHeader('X-Accel-Buffering', 'no');
    response.flushHeaders();
    // A disconnecting client only ends its subscription; the task keeps running and can be
    // re-attached with SubscribeToTask.
    const keepAlive = setInterval(() => response.write(': keep-alive\n\n'), KEEP_ALIVE_MS);
    try {
      for (
        let next = first;
        !next.done && !disconnected.signal.aborted;
        next = await events.next()
      ) {
        response.write(formatSSEEvent(next.value));
      }
      if (disconnected.signal.aborted) {
        await events.return?.(undefined);
      }
    } finally {
      clearInterval(keepAlive);
      response.end();
    }
  }
}
