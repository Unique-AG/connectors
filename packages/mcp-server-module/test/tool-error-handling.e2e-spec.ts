import { type INestApplication, Injectable } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { OpenTelemetryModule } from 'nestjs-otel';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import * as z from 'zod';
import { McpModule, Tool, ToolError } from '../src';

@Injectable()
class ErrorThrowingTools {
  @Tool({
    name: 'throw-internal-error',
    description: 'Always throws an internal error with sensitive details',
    parameters: z.object({}),
  })
  public throwInternalError(): never {
    throw new Error('internal host x: connection refused at 10.0.0.1:5432');
  }

  @Tool({
    name: 'throw-tool-error',
    description: 'Always throws a user-facing ToolError',
    parameters: z.object({}),
  })
  public throwToolError(): never {
    throw new ToolError('The requested resource was not found.');
  }
}

async function postMcp(
  url: URL,
  message: object,
  sessionId?: string,
): Promise<{ status: number; sessionId: string | null; body: string }> {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      accept: 'application/json, text/event-stream',
      'mcp-protocol-version': '2025-06-18',
      ...(sessionId && { 'mcp-session-id': sessionId }),
    },
    body: JSON.stringify(message),
  });
  return {
    status: response.status,
    sessionId: response.headers.get('mcp-session-id'),
    body: await response.text(),
  };
}

async function callTool(url: URL, sessionId: string, toolName: string): Promise<string> {
  const { body } = await postMcp(
    url,
    {
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: { name: toolName, arguments: {} },
    },
    sessionId,
  );
  return body;
}

describe('MCP tool error handling (E2E)', () => {
  let app: INestApplication;
  let url: URL;
  let sessionId: string;

  beforeEach(async () => {
    const moduleFixture = await Test.createTestingModule({
      imports: [
        OpenTelemetryModule.forRoot(),
        McpModule.forRoot({
          name: 'test-mcp',
          version: '1.0.0',
          streamableHttp: { enableJsonResponse: false, statelessMode: false },
        }),
      ],
      providers: [ErrorThrowingTools],
    }).compile();

    app = moduleFixture.createNestApplication({ logger: false });
    await app.listen(0, '127.0.0.1');
    url = new URL(`${await app.getUrl()}/mcp`);

    const { sessionId: sid } = await postMcp(url, {
      jsonrpc: '2.0',
      id: 0,
      method: 'initialize',
      params: {
        protocolVersion: '2025-06-18',
        capabilities: {},
        clientInfo: { name: 'test-client', version: '1.0.0' },
      },
    });
    sessionId = sid as string;
  });

  afterEach(async () => {
    await app.close();
  });

  it('does not leak internal error details for unexpected errors', async () => {
    const body = await callTool(url, sessionId, 'throw-internal-error');
    expect(body).not.toContain('internal host x');
    expect(body).toContain('An unexpected error occurred. Please try again.');
  });

  it('passes the ToolError message through to the client', async () => {
    const body = await callTool(url, sessionId, 'throw-tool-error');
    expect(body).toContain('The requested resource was not found.');
  });
});
