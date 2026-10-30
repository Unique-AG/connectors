import type { CanActivate, ExecutionContext, INestApplication } from '@nestjs/common';
import { Injectable } from '@nestjs/common';
import { Test, type TestingModule } from '@nestjs/testing';
import { OpenTelemetryModule } from 'nestjs-otel';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import * as z from 'zod';
import { McpModule, Tool } from '../src';

@Injectable()
class UserIdGuard implements CanActivate {
  public canActivate(context: ExecutionContext): boolean {
    const req = context
      .switchToHttp()
      .getRequest<{ headers: Record<string, string>; user?: { userProfileId: string } }>();
    const userId = req.headers['x-test-user-id'];
    if (userId) {
      req.user = { userProfileId: userId };
    }
    return true;
  }
}

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

async function postMcp(
  url: URL,
  userId: string,
  message: object,
): Promise<{ status: number; body: Record<string, unknown> }> {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      accept: 'application/json, text/event-stream',
      'mcp-protocol-version': '2025-06-18',
      'x-test-user-id': userId,
    },
    body: JSON.stringify(message),
  });
  const text = await res.text();
  const body = text.startsWith('data:')
    ? (JSON.parse(
        text
          .slice(text.indexOf('\n') + 1)
          .split('data:')[1]
          .trim(),
      ) as Record<string, unknown>)
    : (JSON.parse(text) as Record<string, unknown>);
  return { status: res.status, body };
}

function callEcho(url: URL, userId: string, id: number, msg: string) {
  return postMcp(url, userId, {
    jsonrpc: '2.0',
    id,
    method: 'tools/call',
    params: { name: 'echo', arguments: { msg } },
  });
}

describe('per-user rate limiting', () => {
  let app: INestApplication;
  let url: URL;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      imports: [
        OpenTelemetryModule.forRoot(),
        McpModule.forRoot({
          name: 'rate-limit-test',
          version: '1.0.0',
          rateLimit: { toolCallsPerWindow: 2, windowMs: 60_000 },
          guards: [UserIdGuard],
          streamableHttp: { enableJsonResponse: true, statelessMode: true },
        }),
      ],
      providers: [UserIdGuard, EchoTool],
    }).compile();

    app = module.createNestApplication();
    await app.listen(0);
    const address = app.getHttpServer().address() as { port: number };
    url = new URL(`http://localhost:${address.port}/mcp`);
  });

  afterEach(async () => {
    await app.close();
  });

  it('allows calls within the limit', async () => {
    const first = await callEcho(url, 'user-a', 1, 'hello');
    const second = await callEcho(url, 'user-a', 2, 'world');

    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect(first.body.error).toBeUndefined();
    expect(second.body.error).toBeUndefined();
  });

  it('rejects the call that exceeds the per-user limit', async () => {
    await callEcho(url, 'user-b', 1, 'a');
    await callEcho(url, 'user-b', 2, 'b');
    const limited = await callEcho(url, 'user-b', 3, 'c');

    expect(limited.status).toBe(200);
    const error = limited.body.error as { message: string } | undefined;
    expect(error?.message).toContain('Rate limit exceeded');
  });

  it('serves a different user while another is rate-limited', async () => {
    await callEcho(url, 'user-c', 1, 'a');
    await callEcho(url, 'user-c', 2, 'b');
    await callEcho(url, 'user-c', 3, 'c'); // user-c now rate-limited

    const userDCall = await callEcho(url, 'user-d', 4, 'hello');

    expect(userDCall.status).toBe(200);
    expect(userDCall.body.error).toBeUndefined();
    const result = userDCall.body.result as { content: Array<{ text: string }> } | undefined;
    expect(result?.content[0]?.text).toBe('"hello"');
  });
});
