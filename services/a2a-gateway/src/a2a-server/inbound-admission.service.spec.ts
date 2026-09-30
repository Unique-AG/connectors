import assert from 'node:assert';
import { type SendMessageRequest, TaskState } from '@a2a-js/sdk';
import { ServerCallContext } from '@a2a-js/sdk/server';
import { describe, expect, it, vi } from 'vitest';
import type { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import type { GatewayConfig } from '../config/config.js';
import type { ContextRepository } from '../drizzle/context.repository.js';
import { InboundAdmissionService } from './inbound-admission.service.js';
import type { PgTaskStore } from './pg-task.store.js';

const context = new ServerCallContext({
  tenant: 'company-1',
  user: { isAuthenticated: true, userName: 'user-1' },
  state: new Map<string, unknown>([['publicationId', 'pub-1']]),
});

function request(message: Partial<SendMessageRequest['message']>): SendMessageRequest {
  return {
    message: {
      messageId: 'msg-1',
      contextId: '',
      taskId: '',
      role: 1,
      parts: [
        {
          content: { $case: 'text', value: 'Hello' },
          metadata: undefined,
          filename: '',
          mediaType: '',
        },
      ],
      metadata: undefined,
      extensions: [],
      referenceTaskIds: [],
      ...message,
    },
  } as SendMessageRequest;
}

function subject() {
  const authorization = { publication: vi.fn() };
  const contexts = { create: vi.fn(), findOwned: vi.fn() };
  const taskStore = { reserve: vi.fn(), load: vi.fn(), findByClientMessage: vi.fn() };
  return {
    service: new InboundAdmissionService(
      authorization as unknown as ResourceAuthorizationService,
      contexts as unknown as ContextRepository,
      taskStore as unknown as PgTaskStore,
      { maxRemoteFileBytes: 1024 } as GatewayConfig,
    ),
    authorization,
    contexts,
    taskStore,
  };
}

describe('InboundAdmissionService', () => {
  it('checks new-use authorization and reserves a submitted task', async () => {
    const { service, authorization, taskStore } = subject();

    const admitted = await service.admit(request({}), context);

    expect(authorization.publication).toHaveBeenCalledWith(
      expect.objectContaining({ companyId: 'company-1', userId: 'user-1' }),
      'pub-1',
      true,
    );
    assert.ok('params' in admitted);
    expect(taskStore.reserve).toHaveBeenCalledWith(
      expect.objectContaining({
        id: admitted.params.message?.taskId,
        status: expect.objectContaining({ state: TaskState.TASK_STATE_SUBMITTED }),
      }),
      context,
      'msg-1',
    );
  });

  it('rejects a client-supplied context the caller does not own', async () => {
    const { service, taskStore } = subject();

    await expect(
      service.admit(request({ contextId: 'ctx_foreign' }), context),
    ).rejects.toMatchObject({ name: 'RequestMalformedError' });
    expect(taskStore.reserve).not.toHaveBeenCalled();
  });

  it('reports a busy context when another task is active', async () => {
    const { service, contexts, taskStore } = subject();
    contexts.findOwned.mockResolvedValue({ id: 'ctx_1' });
    taskStore.reserve.mockRejectedValue(
      new Error('insert failed', {
        cause: { code: '23505', constraint: 'a2a_tasks_one_active_per_context_unique' },
      }),
    );

    await expect(service.admit(request({ contextId: 'ctx_1' }), context)).rejects.toMatchObject({
      name: 'RequestMalformedError',
      reason: 'CONTEXT_BUSY',
    });
  });

  it('returns the existing task for a retried send instead of starting another run', async () => {
    const { service, contexts, taskStore } = subject();
    const existing = { id: 'task_1', status: { state: TaskState.TASK_STATE_WORKING } };
    contexts.findOwned.mockResolvedValue({ id: 'ctx_1' });
    taskStore.findByClientMessage.mockResolvedValue(existing);

    await expect(service.admit(request({ contextId: 'ctx_1' }), context)).resolves.toEqual({
      duplicate: existing,
    });
    expect(taskStore.reserve).not.toHaveBeenCalled();
  });

  it('resolves a concurrent duplicate send through the client message constraint', async () => {
    const { service, contexts, taskStore } = subject();
    const existing = { id: 'task_1', status: { state: TaskState.TASK_STATE_WORKING } };
    contexts.findOwned.mockResolvedValue({ id: 'ctx_1' });
    taskStore.findByClientMessage.mockResolvedValueOnce(undefined).mockResolvedValueOnce(existing);
    taskStore.reserve.mockRejectedValue(
      new Error('insert failed', {
        cause: { code: '23505', constraint: 'a2a_tasks_client_message_unique' },
      }),
    );

    await expect(service.admit(request({ contextId: 'ctx_1' }), context)).resolves.toEqual({
      duplicate: existing,
    });
  });

  it('rejects follow-ups to a task that is not awaiting input', async () => {
    const { service, taskStore } = subject();
    taskStore.load.mockResolvedValue({ status: { state: TaskState.TASK_STATE_WORKING } });

    await expect(service.admit(request({ taskId: 'task_1' }), context)).rejects.toMatchObject({
      name: 'UnsupportedOperationError',
    });
  });

  it('accepts inline files of an allowed type and refuses active content', async () => {
    const { service } = subject();
    const file = (mediaType: string) =>
      request({
        parts: [
          {
            content: { $case: 'raw', value: Buffer.from('a,b') },
            metadata: undefined,
            filename: '../data.csv',
            mediaType,
          },
        ],
      } as never);

    await expect(service.admit(file('text/csv'), context)).resolves.toHaveProperty('params');
    await expect(service.admit(file('text/html'), context)).rejects.toMatchObject({
      name: 'ContentTypeNotSupportedError',
    });
  });

  it('rejects unsupported parts before creating a context', async () => {
    const { service, contexts } = subject();

    await expect(
      service.admit(
        request({
          parts: [
            {
              content: { $case: 'url', value: 'https://example.com/file' },
              metadata: undefined,
              filename: '',
              mediaType: '',
            },
          ],
        } as never),
        context,
      ),
    ).rejects.toMatchObject({ name: 'ContentTypeNotSupportedError' });
    expect(contexts.create).not.toHaveBeenCalled();
  });
});
