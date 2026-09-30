import { TaskState } from '@a2a-js/sdk';
import {
  AgentEvent,
  type ExecutionEventBus,
  InMemoryTaskStore,
  type RequestContext,
} from '@a2a-js/sdk/server';
import { describe, expect, it, vi } from 'vitest';
import type { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import type { ContextRepository } from '../drizzle/context.repository.js';
import { A2aSdkService } from './a2a-sdk.service.js';
import { InboundAdmissionService } from './inbound-admission.service.js';
import type { InboundAgentExecutor } from './inbound-agent.executor.js';
import type { PgTaskStore } from './pg-task.store.js';
import type { PublicationService } from './publication.service.js';

const identity = { companyId: 'company-1', userId: 'user-1', roles: [] };

function subject() {
  const taskStore = new InMemoryTaskStore();
  const authorization = { publication: vi.fn() };
  const contexts = { create: vi.fn(), findOwned: vi.fn() };
  const executor = {
    execute: vi.fn(async (request: RequestContext, bus: ExecutionEventBus) => {
      bus.publish(
        AgentEvent.task({
          ...(request.task ?? { artifacts: [], history: [], metadata: undefined }),
          id: request.taskId,
          contextId: request.contextId,
          status: {
            state: TaskState.TASK_STATE_COMPLETED,
            message: undefined,
            timestamp: new Date().toISOString(),
          },
        }),
      );
    }),
    cancelTask: vi.fn(),
  };
  const publications = {
    getTenantAgentCard: vi.fn().mockResolvedValue({
      name: 'Agent',
      description: 'Agent',
      supportedInterfaces: [],
      version: '1',
      capabilities: { streaming: true, pushNotifications: false, extendedAgentCard: true },
      securitySchemes: {},
      securityRequirements: [],
      defaultInputModes: ['text/plain'],
      defaultOutputModes: ['text/plain'],
      skills: [],
      signatures: [],
    }),
  };
  const admission = new InboundAdmissionService(
    authorization as unknown as ResourceAuthorizationService,
    contexts as unknown as ContextRepository,
    taskStore as unknown as PgTaskStore,
  );
  return {
    service: new A2aSdkService(
      admission,
      authorization as unknown as ResourceAuthorizationService,
      executor as unknown as InboundAgentExecutor,
      publications as unknown as PublicationService,
      taskStore as unknown as PgTaskStore,
    ),
    authorization,
    contexts,
    executor,
  };
}

function call(service: A2aSdkService, method: string, params: Record<string, unknown>) {
  return service.handleJsonRpc({
    body: { jsonrpc: '2.0', id: 1, method, params },
    headers: {},
    identity,
    publicationId: 'pub-1',
  });
}

describe('A2aSdkService', () => {
  it('starts a first message in a new server-generated context and task', async () => {
    const { service, contexts, executor } = subject();

    const response = await call(service, 'SendMessage', {
      message: { messageId: 'msg-1', role: 'ROLE_USER', parts: [{ text: 'Hello' }] },
    });

    expect(response).toMatchObject({
      result: {
        task: {
          id: expect.stringMatching(/^task_/),
          contextId: expect.stringMatching(/^ctx_/),
          status: { state: 'TASK_STATE_COMPLETED' },
        },
      },
    });
    expect(contexts.create).toHaveBeenCalledWith(identity, 'pub-1', expect.stringMatching(/^ctx_/));
    expect(executor.execute).toHaveBeenCalledTimes(1);
  });

  it('rejects malformed messages before any context or run is created', async () => {
    const { service, contexts, executor } = subject();

    const response = await call(service, 'SendMessage', {
      message: { messageId: 'msg-1', role: 'ROLE_USER', parts: [{ text: '  ' }] },
    });

    expect(response).toMatchObject({ error: { code: -32602 } });
    expect(contexts.create).not.toHaveBeenCalled();
    expect(executor.execute).not.toHaveBeenCalled();
  });

  it('requires access to the space for the extended card', async () => {
    const { service, authorization } = subject();

    await call(service, 'GetExtendedAgentCard', {});

    expect(authorization.publication).toHaveBeenCalledWith(identity, 'pub-1');
  });
});
