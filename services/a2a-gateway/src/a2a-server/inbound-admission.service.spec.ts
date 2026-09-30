import { type SendMessageRequest, TaskState } from '@a2a-js/sdk';
import { ServerCallContext } from '@a2a-js/sdk/server';
import { describe, expect, it, vi } from 'vitest';
import type { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
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
  const taskStore = { save: vi.fn(), load: vi.fn() };
  return {
    service: new InboundAdmissionService(
      authorization as unknown as ResourceAuthorizationService,
      contexts as unknown as ContextRepository,
      taskStore as unknown as PgTaskStore,
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
    expect(taskStore.save).toHaveBeenCalledWith(
      expect.objectContaining({
        id: admitted.message?.taskId,
        status: expect.objectContaining({ state: TaskState.TASK_STATE_SUBMITTED }),
      }),
      context,
    );
  });

  it('rejects a client-supplied context the caller does not own', async () => {
    const { service, taskStore } = subject();

    await expect(
      service.admit(request({ contextId: 'ctx_foreign' }), context),
    ).rejects.toMatchObject({ name: 'RequestMalformedError' });
    expect(taskStore.save).not.toHaveBeenCalled();
  });

  it('reports a busy context when another task is active', async () => {
    const { service, contexts, taskStore } = subject();
    contexts.findOwned.mockResolvedValue({ id: 'ctx_1' });
    taskStore.save.mockRejectedValue(
      new Error('insert failed', {
        cause: { code: '23505', constraint: 'a2a_tasks_one_active_per_context_unique' },
      }),
    );

    await expect(service.admit(request({ contextId: 'ctx_1' }), context)).rejects.toMatchObject({
      name: 'RequestMalformedError',
      reason: 'CONTEXT_BUSY',
    });
  });

  it('rejects follow-ups to a task that is not awaiting input', async () => {
    const { service, taskStore } = subject();
    taskStore.load.mockResolvedValue({ status: { state: TaskState.TASK_STATE_WORKING } });

    await expect(service.admit(request({ taskId: 'task_1' }), context)).rejects.toMatchObject({
      name: 'UnsupportedOperationError',
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
