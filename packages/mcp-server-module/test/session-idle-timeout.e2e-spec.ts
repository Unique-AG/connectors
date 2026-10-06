import { setTimeout as sleep } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { type INestApplication, Injectable } from '@nestjs/common';
import { Test, type TestingModule } from '@nestjs/testing';
import { OpenTelemetryModule } from 'nestjs-otel';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import * as z from 'zod';
import { McpModule, McpStreamableHttpService, Tool } from '../src';

const SESSION_IDLE_TIMEOUT_MS = 200;

@Injectable()
class WaitTool {
  @Tool({
    name: 'wait',
    description: 'Resolves after the given number of milliseconds',
    parameters: z.object({ ms: z.number() }),
  })
  public async wait({ ms }: { ms: number }): Promise<string> {
    await sleep(ms);
    return 'done';
  }
}

// Like the prod clients: no GET SSE stream and no DELETE.
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

async function initializeSession(url: URL): Promise<string> {
  const { status, sessionId } = await postMcp(url, {
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: {
      protocolVersion: '2025-06-18',
      capabilities: {},
      clientInfo: { name: 'test-client', version: '1.0.0' },
    },
  });
  expect(status).toBe(200);
  expect(sessionId).toBeTruthy();
  return sessionId as string;
}

async function listToolsStatus(url: URL, sessionId: string): Promise<number> {
  const { status } = await postMcp(url, { jsonrpc: '2.0', id: 2, method: 'tools/list' }, sessionId);
  return status;
}

function compileModule(sessionIdleTimeoutMs: number): Promise<TestingModule> {
  return Test.createTestingModule({
    imports: [
      OpenTelemetryModule.forRoot(),
      McpModule.forRoot({
        name: 'test-mcp',
        version: '1.0.0',
        streamableHttp: { enableJsonResponse: false, statelessMode: false, sessionIdleTimeoutMs },
      }),
    ],
    providers: [WaitTool],
  }).compile();
}

describe('MCP stateful session idle timeout (E2E)', () => {
  let app: INestApplication;
  let url: URL;

  beforeEach(async () => {
    const moduleFixture = await compileModule(SESSION_IDLE_TIMEOUT_MS);
    app = moduleFixture.createNestApplication({ logger: false });
    await app.listen(0, '127.0.0.1');
    url = new URL(`${await app.getUrl()}/mcp`);
  });

  afterEach(async () => {
    await app.close();
  });

  it('closes a session that has been idle longer than the timeout', async () => {
    const sessionId = await initializeSession(url);
    expect(await listToolsStatus(url, sessionId)).toBe(200);

    // Requests count as activity, so stay silent.
    await sleep(SESSION_IDLE_TIMEOUT_MS * 3);

    expect(await listToolsStatus(url, sessionId)).toBe(404);
  });

  it('keeps a session open while one of its requests is still running', async () => {
    const sessionId = await initializeSession(url);

    const { status, body } = await postMcp(
      url,
      {
        jsonrpc: '2.0',
        id: 3,
        method: 'tools/call',
        params: { name: 'wait', arguments: { ms: SESSION_IDLE_TIMEOUT_MS * 4 } },
      },
      sessionId,
    );

    expect(status).toBe(200);
    expect(body).toContain('done');
    expect(await listToolsStatus(url, sessionId)).toBe(200);
  });

  it('keeps a session open while the client holds its SSE stream', async () => {
    const client = new Client({ name: 'test-client', version: '1.0.0' });
    const transport = new StreamableHTTPClientTransport(url);
    await client.connect(transport);

    await sleep(SESSION_IDLE_TIMEOUT_MS * 4);

    await expect(client.listTools()).resolves.toMatchObject({ tools: [{ name: 'wait' }] });
    await client.close();
  });

  it('disconnects the MCP server of a session it closes', async () => {
    const sessionId = await initializeSession(url);
    const { mcpServers } = app.get(McpStreamableHttpService) as unknown as {
      mcpServers: Record<string, McpServer>;
    };
    const mcpServer = mcpServers[sessionId];
    expect(mcpServer?.isConnected()).toBe(true);

    await sleep(SESSION_IDLE_TIMEOUT_MS * 3);

    expect(mcpServer?.isConnected()).toBe(false);
  });

  it.each(['GET', 'DELETE'])('answers %s with 404 for an unknown session', async (method) => {
    const response = await fetch(url, {
      method,
      headers: {
        accept: 'application/json, text/event-stream',
        'mcp-session-id': 'expired-session',
        'mcp-protocol-version': '2025-06-18',
      },
    });

    expect(response.status).toBe(404);
    expect(await response.json()).toMatchObject({ error: { message: 'Session not found' } });
  });
});

describe('MCP session idle timeout option', () => {
  it.each([0, -1, Number.NaN])('rejects sessionIdleTimeoutMs = %s', async (timeoutMs) => {
    await expect(compileModule(timeoutMs)).rejects.toThrow(/sessionIdleTimeoutMs/);
  });
});
