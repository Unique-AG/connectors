import { TaskState } from '@a2a-js/sdk';
import { ServerCallContext } from '@a2a-js/sdk/server';
import { describe, expect, it, vi } from 'vitest';
import { type GatewayConfig, loadConfig } from '../config/config.js';
import type { CredentialVault } from '../credentials/credential-vault.js';
import { EgressService } from '../credentials/egress.service.js';
import type { GatewayDatabase } from '../drizzle/drizzle.module.js';
import { CallbackWakeups } from '../outbound/callback-wakeups.service.js';
import type { WorkflowService } from '../workflow/workflow.service.js';
import { PgPushNotificationStore } from './pg-push-notification.store.js';
import type { PgTaskStore } from './pg-task.store.js';
import { DurablePushNotificationSender } from './push-notification.sender.js';

function config(environment: Record<string, string> = {}): GatewayConfig {
  return loadConfig({
    NODE_ENV: 'test',
    DATABASE_URL: 'postgresql://localhost/a2a',
    AMQP_URL: 'amqp://localhost',
    PUBLIC_BASE_URL: 'https://gateway.example/',
    ZITADEL_ISSUER: 'https://identity.example/',
    UNIQUE_CHAT_URL: 'http://node-chat/',
    UNIQUE_SCOPE_MANAGEMENT_URL: 'http://scope-management/',
    UNIQUE_INGESTION_URL: 'http://node-ingestion/',
    ENCRYPTION_KEY: '11'.repeat(32),
    PUSH_NOTIFICATIONS_ENABLED: 'true',
    ...environment,
  });
}

const context = new ServerCallContext({
  tenant: 'company-1',
  user: { isAuthenticated: true, userName: 'user-1' },
  state: new Map(),
});

function pushConfig(url: string) {
  return {
    tenant: '',
    id: '',
    taskId: 'task-1',
    url,
    token: 'client-token',
    authentication: { scheme: 'Bearer', credentials: 'client-secret' },
  };
}

function store(taskExists = true) {
  const insert = vi.fn().mockReturnValue({
    values: vi.fn().mockReturnValue({ onConflictDoUpdate: vi.fn() }),
  });
  const database = {
    select: vi.fn().mockReturnValue({
      from: vi.fn().mockReturnValue({ where: vi.fn().mockResolvedValue([{ value: 0 }]) }),
    }),
    insert,
  };
  const vault = { seal: vi.fn().mockReturnValue(Buffer.from('sealed')), open: vi.fn() };
  return {
    insert,
    vault,
    store: new PgPushNotificationStore(
      database as unknown as GatewayDatabase,
      new EgressService(config()),
      {
        load: vi.fn().mockResolvedValue(taskExists ? { id: 'task-1' } : undefined),
      } as unknown as PgTaskStore,
      vault as unknown as CredentialVault,
    ),
  };
}

describe('push notification configs', () => {
  it('stores an allowed webhook with encrypted credentials and assigns an id', async () => {
    const { store: subject, vault, insert } = store();
    const registration = pushConfig('https://hooks.example/a2a');
    await subject.save('task-1', context, registration);
    expect(registration.id).toMatch(/^pnc_/);
    expect(JSON.parse(String(vault.seal.mock.calls[0]?.[0]))).toEqual({
      token: 'client-token',
      scheme: 'Bearer',
      credentials: 'client-secret',
    });
    expect(insert).toHaveBeenCalled();
  });

  it.each([
    'http://hooks.example/a2a',
    'https://127.0.0.1/a2a',
    'https://169.254.169.254/latest',
    'https://user:pass@hooks.example/a2a',
  ])('refuses the webhook %s', async (url) => {
    const { store: subject, insert } = store();
    await expect(subject.save('task-1', context, pushConfig(url))).rejects.toMatchObject({
      name: 'RequestMalformedError',
    });
    expect(insert).not.toHaveBeenCalled();
  });

  it('refuses registrations for tasks the caller does not own', async () => {
    const { store: subject } = store(false);
    await expect(
      subject.save('task-1', context, pushConfig('https://hooks.example/a2a')),
    ).rejects.toMatchObject({ name: 'TaskNotFoundError' });
  });
});

describe('DurablePushNotificationSender', () => {
  function sender(enabled = true) {
    const targets = [
      { id: 'pnc-1', url: 'https://hooks.example/a2a', token: 't', scheme: '', credentials: '' },
    ];
    const pushStore = {
      targets: vi.fn().mockResolvedValue(targets),
      target: vi.fn().mockResolvedValue(targets[0]),
      recordDelivery: vi.fn(),
    };
    const workflow = { register: vi.fn(), spawn: vi.fn() };
    const egress = { postWebhook: vi.fn().mockResolvedValue(new Response(null, { status: 500 })) };
    const subject = new DurablePushNotificationSender(
      pushStore as unknown as PgPushNotificationStore,
      egress as unknown as EgressService,
      workflow as unknown as WorkflowService,
      config({ PUSH_NOTIFICATIONS_ENABLED: String(enabled) }),
    );
    subject.onModuleInit();
    return { subject, pushStore, workflow, egress };
  }

  it('spawns one deduplicated, content-free delivery per webhook and state', async () => {
    const { subject, workflow } = sender();
    await subject.notify('company-1', 'task-1', 'ctx-1', TaskState.TASK_STATE_COMPLETED);
    expect(workflow.spawn).toHaveBeenCalledWith(
      'push.deliver',
      expect.objectContaining({ configId: 'pnc-1', state: 'TASK_STATE_COMPLETED' }),
      expect.objectContaining({ idempotencyKey: expect.any(String), maxAttempts: 6 }),
    );
    expect(JSON.stringify(workflow.spawn.mock.calls)).not.toContain('artifacts');
  });

  it('does nothing when push notifications are disabled', async () => {
    const { subject, workflow } = sender(false);
    await subject.notify('company-1', 'task-1', 'ctx-1', TaskState.TASK_STATE_COMPLETED);
    expect(workflow.spawn).not.toHaveBeenCalled();
  });

  it('records a failed delivery and throws so absurd retries with backoff', async () => {
    const { workflow, pushStore } = sender();
    const deliver = workflow.register.mock.calls[0]?.[1] as (params: unknown) => Promise<unknown>;
    await expect(
      deliver({
        companyId: 'company-1',
        configId: 'pnc-1',
        taskId: 'task-1',
        contextId: 'c',
        state: 'X',
        timestamp: '',
      }),
    ).rejects.toThrow('delivery failed');
    expect(pushStore.recordDelivery).toHaveBeenCalledWith('company-1', 'pnc-1', false, 10);
  });
});

describe('outbound callbacks', () => {
  it('accepts only the per-execution token', () => {
    const wakeups = new CallbackWakeups(config());
    expect(wakeups.verify('exec-1', wakeups.token('exec-1'))).toBe(true);
    expect(wakeups.verify('exec-2', wakeups.token('exec-1'))).toBe(false);
    expect(wakeups.verify('exec-1', undefined)).toBe(false);
    expect(wakeups.callbackUrl('exec-1')).toBe('https://gateway.example/a2a/callbacks/exec-1');
  });
});
