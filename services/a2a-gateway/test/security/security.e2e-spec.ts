/**
 * Security boundary matrix over HTTP against the real gateway (Kong auth mode, PostgreSQL,
 * RabbitMQ, absurd) with the stub core as permission authority. Needs a migrated,
 * absurd-initialised database: E2E_DATABASE_URL and E2E_AMQP_URL (see test/tck/run-tck.sh).
 */
import assert from 'node:assert';
import type { INestApplication } from '@nestjs/common';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
  EXTERNAL_ASSISTANT_ID,
  startStubCore,
  TCK_ASSISTANT_ID,
  TCK_COLLEAGUE,
  TCK_COMPANY,
  TCK_MANAGER,
} from '../fixtures/stub-core.js';

const databaseUrl = process.env.E2E_DATABASE_URL;

interface RpcResponse {
  result?: { id?: string; task?: { id: string; contextId: string } };
  error?: { code: number; message: string };
}

interface Caller {
  companyId: string;
  userId: string;
}

const manager: Caller = { companyId: TCK_COMPANY, userId: TCK_MANAGER };
const colleague: Caller = { companyId: TCK_COMPANY, userId: TCK_COLLEAGUE };
const outsider: Caller = { companyId: TCK_COMPANY, userId: 'tck-outsider' };
const otherCompany: Caller = { companyId: 'other-company', userId: TCK_MANAGER };

describe.skipIf(!databaseUrl)('gateway security boundaries', () => {
  let app: INestApplication;
  let core: Awaited<ReturnType<typeof startStubCore>>;
  let base: string;
  let publicationId: string;
  let taskId: string;
  let contextId: string;

  const call = (path: string, init: RequestInit & { as?: Caller } = {}) => {
    const { as, headers, ...rest } = init;
    return fetch(`${base}${path}`, {
      ...rest,
      headers: {
        'content-type': 'application/json',
        ...(as ? { 'x-company-id': as.companyId, 'x-user-id': as.userId } : {}),
        ...headers,
      },
    });
  };
  const rpc = async (as: Caller | undefined, method: string, params: unknown) => {
    const response = await call(`/a2a/agents/${publicationId}`, {
      method: 'POST',
      as,
      headers: { 'a2a-version': '1.0' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
    });
    return { status: response.status, body: (await response.json()) as RpcResponse };
  };
  const send = (as: Caller, text: string, extra: Record<string, unknown> = {}) =>
    rpc(as, 'SendMessage', {
      message: { role: 'ROLE_USER', messageId: crypto.randomUUID(), parts: [{ text }], ...extra },
      configuration: { returnImmediately: false },
    });

  beforeAll(async () => {
    core = await startStubCore();
    Object.assign(process.env, {
      NODE_ENV: 'test',
      AUTH_MODE: 'kong',
      DATABASE_URL: databaseUrl,
      AMQP_URL: process.env.E2E_AMQP_URL,
      PUBLIC_BASE_URL: 'https://a2a.example',
      ZITADEL_ISSUER: 'https://id.example',
      UNIQUE_CHAT_URL: core.url,
      UNIQUE_SCOPE_MANAGEMENT_URL: core.url,
      UNIQUE_INGESTION_URL: core.url,
      ENCRYPTION_KEY: '11'.repeat(32),
      // Set explicitly: the instrumentation package loads a local .env for unset keys.
      EGRESS_ALLOWED_HOSTS: 'localhost',
      EGRESS_ALLOW_INSECURE: 'false',
      PUSH_NOTIFICATIONS_ENABLED: 'true',
      PUSH_ALLOWED_HOSTS: 'hooks.example',
      OTEL_METRICS_EXPORTER: 'none',
      OTEL_TRACES_EXPORTER: 'none',
    });
    const { NestFactory } = await import('@nestjs/core');
    const { AppModule } = await import('../../src/app.module.js');
    const { GATEWAY_CONFIG } = await import('../../src/config/config.js');
    app = await NestFactory.create(AppModule, { bodyParser: false, logger: false });
    // Same body limit as main.ts.
    app.useBodyParser('json', { limit: app.get(GATEWAY_CONFIG).maxRequestBytes });
    await app.listen(0, '127.0.0.1');
    base = await app.getUrl();

    const published = await call(`/management/publications/${TCK_ASSISTANT_ID}`, {
      method: 'PUT',
      as: manager,
      body: JSON.stringify({ enabled: true, card: { name: 'TCK space', description: 'e2e' } }),
    });
    expect(published.status).toBe(200);
    publicationId = ((await published.json()) as { id: string }).id;

    const { body } = await send(manager, 'hello');
    assert.ok(body.result?.task, 'the setup task was not created');
    taskId = body.result.task.id;
    contextId = body.result.task.contextId;
  }, 60_000);

  afterAll(async () => {
    await app?.close();
    await core?.close();
  });

  describe('identity', () => {
    it.each([
      ['GET', '/a2a/agents'],
      ['POST', '/a2a/agents/pub_x'],
      ['GET', '/a2a/agents/pub_x/files/cont_x?taskId=task_x'],
      ['GET', `/management/publications/${TCK_ASSISTANT_ID}`],
      ['PUT', `/management/publications/${TCK_ASSISTANT_ID}`],
      ['DELETE', `/management/publications/${TCK_ASSISTANT_ID}`],
      ['GET', '/management/connections'],
      ['POST', '/management/connections'],
      ['GET', '/management/usage'],
      ['GET', '/internal/capabilities'],
      ['POST', '/internal/executions'],
    ])('rejects %s %s without Kong-stamped identity', async (method, path) => {
      const response = await call(path, { method, body: method === 'GET' ? undefined : '{}' });
      expect(response.status).toBe(401);
    });

    it('ignores a bearer token: the gateway never validates JWTs itself', async () => {
      const response = await call('/a2a/agents', {
        headers: { authorization: 'Bearer forged.token.value' },
      });
      expect(response.status).toBe(401);
    });

    it('refuses service identities', async () => {
      const response = await call('/a2a/agents', {
        as: manager,
        headers: { 'x-service-id': 'service' },
      });
      expect(response.status).toBe(401);
    });

    it('serves the public card without tenant internals', async () => {
      const response = await call(`/a2a/agents/${publicationId}/.well-known/agent-card.json`);
      const card = await response.text();
      expect(response.status).toBe(200);
      expect(card).not.toContain(TCK_COMPANY);
      expect(card).not.toContain(TCK_ASSISTANT_ID);
    });
  });

  describe('tenancy', () => {
    it.each([
      ['a colleague with space access', colleague],
      ['a user without space access', outsider],
      ['another company', otherCompany],
    ])('hides a task from %s', async (_who, caller) => {
      for (const [method, params] of [
        ['GetTask', { id: taskId }],
        ['CancelTask', { id: taskId }],
        ['SubscribeToTask', { id: taskId }],
      ] as const) {
        const { body } = await rpc(caller, method, params);
        expect(body.result, method).toBeUndefined();
        expect(body.error, method).toBeDefined();
      }
      const listed = await rpc(caller, 'ListTasks', {});
      expect(JSON.stringify(listed.body)).not.toContain(taskId);
    });

    it('refuses to continue another user’s context', async () => {
      const { body } = await send(colleague, 'hijack', { contextId });
      expect(body.error).toBeDefined();
    });

    it.each([
      ['a user without space access', outsider],
      ['another company', otherCompany],
    ])('refuses new work from %s', async (_who, caller) => {
      const { body } = await send(caller, 'hello');
      expect(body.error).toBeDefined();
    });

    it('lists the catalog only for callers with access', async () => {
      const allowed = await (await call('/a2a/agents', { as: colleague })).text();
      expect(allowed).toContain(publicationId);
      for (const caller of [outsider, otherCompany]) {
        const denied = await call('/a2a/agents', { as: caller });
        expect(await denied.text()).not.toContain(publicationId);
      }
    });

    it('refuses file downloads outside the caller’s task', async () => {
      const response = await call(
        `/a2a/agents/${publicationId}/files/cont_x?taskId=${encodeURIComponent(taskId)}`,
        { as: colleague },
      );
      expect(response.status).toBe(404);
    });

    it.each([
      ['a non-manager', colleague],
      ['another company', otherCompany],
    ])('refuses publication management to %s', async (_who, caller) => {
      const read = await call(`/management/publications/${TCK_ASSISTANT_ID}`, { as: caller });
      expect([403, 404]).toContain(read.status);
      const write = await call(`/management/publications/${TCK_ASSISTANT_ID}`, {
        method: 'PUT',
        as: caller,
        body: JSON.stringify({ enabled: false, card: { name: 'taken over', description: 'x' } }),
      });
      expect([403, 404]).toContain(write.status);
      const card = await call(`/a2a/agents/${publicationId}/.well-known/agent-card.json`);
      expect(await card.text()).not.toContain('taken over');
    });

    it('does not let another company see connections or usage', async () => {
      const connections = await call('/management/connections', { as: otherCompany });
      expect([403, 404]).toContain(connections.status);
      const usage = await call('/management/usage', { as: otherCompany });
      expect([403, 404]).toContain(usage.status);
    });
  });

  describe('gates', () => {
    it('never publishes an external (A2A-provider) space', async () => {
      const response = await call(`/management/publications/${EXTERNAL_ASSISTANT_ID}`, {
        method: 'PUT',
        as: manager,
        body: JSON.stringify({ enabled: true, card: { name: 'relay', description: 'x' } }),
      });
      expect(response.status).toBeGreaterThanOrEqual(400);
    });

    it('refuses new work but keeps existing tasks readable when the rollout flag is off', async () => {
      core.state.a2aEnabled = false;
      try {
        expect((await send(manager, 'hello')).body.error).toBeDefined();
        const publish = await call(`/management/publications/${TCK_ASSISTANT_ID}`, {
          method: 'PUT',
          as: manager,
          body: JSON.stringify({ enabled: true, card: { name: 'TCK space', description: 'x' } }),
        });
        expect(publish.status).toBeGreaterThanOrEqual(400);
        expect((await rpc(manager, 'GetTask', { id: taskId })).body.result?.id).toBe(taskId);
      } finally {
        core.state.a2aEnabled = true;
      }
    });

    it('caps concurrent streams per user and releases them on disconnect', async () => {
      core.state.answerDelayMs = 60_000;
      const { body } = await rpc(manager, 'SendMessage', {
        message: { role: 'ROLE_USER', messageId: crypto.randomUUID(), parts: [{ text: 'slow' }] },
        configuration: { returnImmediately: true },
      });
      core.state.answerDelayMs = 200;
      const subscribe = (signal?: AbortSignal) =>
        call(`/a2a/agents/${publicationId}`, {
          method: 'POST',
          as: manager,
          signal,
          headers: { 'a2a-version': '1.0' },
          body: JSON.stringify({
            jsonrpc: '2.0',
            id: 1,
            method: 'SubscribeToTask',
            params: { id: body.result?.task?.id },
          }),
        });
      const clients = Array.from({ length: 20 }, () => new AbortController());
      const open = await Promise.all(clients.map((client) => subscribe(client.signal)));
      expect(open.map((response) => response.headers.get('content-type'))).toEqual(
        clients.map(() => expect.stringContaining('text/event-stream')),
      );
      expect((await subscribe()).status).toBe(429);
      for (const client of clients) {
        client.abort();
      }
      await expect
        .poll(async () => {
          const retry = new AbortController();
          const response = await subscribe(retry.signal);
          retry.abort();
          return response.status;
        })
        .toBe(200);
    });

    it('rejects oversized request bodies', async () => {
      const response = await call(`/a2a/agents/${publicationId}`, {
        method: 'POST',
        as: manager,
        body: JSON.stringify({ padding: 'x'.repeat(30 * 1024 * 1024) }),
      });
      expect(response.status).toBe(413);
    });
  });

  describe('outbound URLs', () => {
    it.each([
      'https://169.254.169.254/.well-known/agent-card.json',
      'https://agent.not-approved.example/.well-known/agent-card.json',
      'http://localhost/.well-known/agent-card.json',
      'https://user:pass@localhost/.well-known/agent-card.json',
    ])('refuses a connection to %s', async (agentCardUrl) => {
      const response = await call('/management/connections', {
        method: 'POST',
        as: manager,
        body: JSON.stringify({ name: 'x', agentCardUrl, credential: { type: 'none' } }),
      });
      expect(response.status).toBe(400);
    });

    it('blocks an approved host that resolves to a private address and keeps the secret', async () => {
      const created = await call('/management/connections', {
        method: 'POST',
        as: manager,
        body: JSON.stringify({
          name: `private-${crypto.randomUUID()}`,
          agentCardUrl: 'https://localhost/.well-known/agent-card.json',
          credential: { type: 'bearer', token: 'super-secret-token' },
        }),
      });
      expect(created.status).toBe(201);
      const connection = (await created.json()) as { id: string };
      const tested = await call(`/management/connections/${connection.id}/test`, {
        method: 'POST',
        as: manager,
      });
      const body = await tested.text();
      expect(JSON.parse(body)).toMatchObject({ ok: false });
      expect(body).not.toContain('super-secret-token');
      const read = await call(`/management/connections/${connection.id}`, { as: manager });
      expect(await read.text()).not.toContain('super-secret-token');
    });

    it.each([
      'https://169.254.169.254/hook',
      'https://hooks.not-approved.example/hook',
      'http://hooks.example/hook',
      'https://hooks.example:8443/hook',
    ])('refuses a push webhook to %s', async (url) => {
      const { body } = await rpc(manager, 'CreateTaskPushNotificationConfig', {
        taskId,
        url,
        token: 'client-token',
      });
      expect(body.error).toBeDefined();
    });
  });

  describe('callbacks', () => {
    it.each([
      ['no token', {}],
      ['a forged token', { authorization: 'Bearer forged' }],
    ])('rejects a callback with %s', async (_case, headers) => {
      const response = await call('/a2a/callbacks/exec_01h0000000000000000000000', {
        method: 'POST',
        headers,
        body: JSON.stringify({ task: { id: 'remote', status: { state: 'TASK_STATE_COMPLETED' } } }),
      });
      expect([401, 404]).toContain(response.status);
    });
  });
});
