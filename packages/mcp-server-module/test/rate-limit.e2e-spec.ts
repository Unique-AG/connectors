import type { DynamicModule, INestApplication } from '@nestjs/common';
import { Injectable } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { OpenTelemetryModule } from 'nestjs-otel';
import { afterEach, describe, expect, it } from 'vitest';
import * as z from 'zod';
import {
  type HttpRequest,
  McpModule,
  type McpRateLimitConfig,
  type McpRateLimitOptions,
  mcpRateLimitConfigSchema,
  Tool,
} from '../src';

const RATE_LIMIT_CONFIG = 'TEST_RATE_LIMIT_CONFIG';

@Injectable()
class EchoTool {
  @Tool({
    name: 'echo',
    description: 'Echo back the message',
    parameters: z.object({ msg: z.string() }),
  })
  public echo({ msg }: { msg: string }): string {
    return msg;
  }
}

const keyFromHeader = (request: HttpRequest) => String(request.headers['x-test-key']);

// Registered globally, as a service's ConfigModule registers its configs.
function globalRateLimitConfig(config: McpRateLimitConfig): DynamicModule {
  return {
    module: class RateLimitConfigModule {},
    global: true,
    providers: [{ provide: RATE_LIMIT_CONFIG, useValue: config }],
    exports: [RATE_LIMIT_CONFIG],
  };
}

async function startApp(
  rateLimit: McpRateLimitOptions | undefined,
  config: McpRateLimitConfig = { toolCallsPerWindow: 2, windowSeconds: 60 },
): Promise<{ app: INestApplication; url: URL }> {
  const module = await Test.createTestingModule({
    imports: [
      OpenTelemetryModule.forRoot(),
      globalRateLimitConfig(config),
      McpModule.forRoot({
        name: 'rate-limit-test',
        version: '1.0.0',
        rateLimit,
        streamableHttp: { enableJsonResponse: true, statelessMode: true },
      }),
    ],
    providers: [EchoTool],
  }).compile();

  const app = module.createNestApplication();
  await app.listen(0);
  const address = app.getHttpServer().address() as { port: number };
  return { app, url: new URL(`http://localhost:${address.port}/mcp`) };
}

async function callEcho(
  url: URL,
  key: string,
  id: number,
): Promise<{ error?: { message: string }; result?: { content: Array<{ text: string }> } }> {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      accept: 'application/json, text/event-stream',
      'mcp-protocol-version': '2025-06-18',
      'x-test-key': key,
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id,
      method: 'tools/call',
      params: { name: 'echo', arguments: { msg: `call ${id}` } },
    }),
  });
  return (await res.json()) as {
    error?: { message: string };
    result?: { content: Array<{ text: string }> };
  };
}

async function callTimes(url: URL, key: string, times: number) {
  const responses = [];
  for (let id = 1; id <= times; id++) {
    responses.push(await callEcho(url, key, id));
  }
  return responses;
}

describe('per-key rate limiting', () => {
  const limitedByHeader = { config: RATE_LIMIT_CONFIG, getRequestKey: keyFromHeader };
  let app: INestApplication | undefined;

  afterEach(async () => {
    await app?.close();
    app = undefined;
  });

  it('serves calls within the limit', async () => {
    const started = await startApp(limitedByHeader);
    app = started.app;

    const responses = await callTimes(started.url, 'key-a', 2);

    expect(responses.map((response) => response.error)).toEqual([undefined, undefined]);
  });

  it('rejects the call that exceeds the limit of its key', async () => {
    const started = await startApp(limitedByHeader);
    app = started.app;

    const [, , third] = await callTimes(started.url, 'key-a', 3);

    expect(third?.error?.message).toContain('Rate limit exceeded: 2 tool calls per 60 seconds');
  });

  it('serves another key while one is limited', async () => {
    const started = await startApp(limitedByHeader);
    app = started.app;
    await callTimes(started.url, 'key-a', 3);

    const other = await callEcho(started.url, 'key-b', 4);

    expect(other.result?.content[0]?.text).toBe('"call 4"');
  });

  it('does not limit calls when no rate limit is configured', async () => {
    const started = await startApp(undefined);
    app = started.app;

    const responses = await callTimes(started.url, 'key-a', 3);

    expect(responses.map((response) => response.error)).toEqual([undefined, undefined, undefined]);
  });
});

describe('mcpRateLimitConfigSchema', () => {
  it('defaults to 60 tool calls a minute', () => {
    expect(mcpRateLimitConfigSchema.parse({})).toEqual({
      toolCallsPerWindow: 60,
      windowSeconds: 60,
    });
  });

  it('reads the values from environment strings', () => {
    expect(
      mcpRateLimitConfigSchema.parse({ toolCallsPerWindow: '120', windowSeconds: '30' }),
    ).toEqual({ toolCallsPerWindow: 120, windowSeconds: 30 });
  });

  it.each([
    ['a limit of 0', { toolCallsPerWindow: '0' }],
    ['a negative limit', { toolCallsPerWindow: '-1' }],
    ['a fractional limit', { toolCallsPerWindow: '1.5' }],
    ['a limit that is not a number', { toolCallsPerWindow: 'sixty' }],
    ['a zero window', { windowSeconds: '0' }],
  ])('rejects %s', (_case, input) => {
    expect(mcpRateLimitConfigSchema.safeParse(input).success).toBe(false);
  });
});
