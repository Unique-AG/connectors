import { TaskState } from '@a2a-js/sdk';
import { type ExecutionEventBus, type RequestContext, ServerCallContext } from '@a2a-js/sdk/server';
import { describe, expect, it, vi } from 'vitest';
import type { GatewayConfig } from '../config/config.js';
import type { ContextRepository } from '../drizzle/context.repository.js';
import type { PublicationRepository } from '../drizzle/publication.repository.js';
import type { ChatEventConsumer } from '../event-bus/chat-event.consumer.js';
import type { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { InboundAgentExecutor } from './inbound-agent.executor.js';
import { NativeRunObserver } from './native-run-observer.js';
import type { PgTaskStore } from './pg-task.store.js';

type AgentEvent = Parameters<ExecutionEventBus['publish']>[0];

const userMessage = {
  messageId: 'msg-1',
  contextId: 'ctx_1',
  taskId: 'task_1',
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
};

const request = {
  taskId: 'task_1',
  contextId: 'ctx_1',
  userMessage,
  task: {
    id: 'task_1',
    contextId: 'ctx_1',
    status: { state: TaskState.TASK_STATE_SUBMITTED, message: undefined, timestamp: '' },
    artifacts: [],
    history: [userMessage],
    metadata: undefined,
  },
  context: new ServerCallContext({
    tenant: 'company-1',
    user: { isAuthenticated: true, userName: 'user-1' },
    state: new Map<string, unknown>([['publicationId', 'pub-1']]),
  }),
} as unknown as RequestContext;

function subject(unique: Record<string, ReturnType<typeof vi.fn>>) {
  const events: AgentEvent[] = [];
  const client = {
    createMessage: vi.fn().mockResolvedValue({
      id: 'user-msg',
      chatId: 'chat-1',
      messages: [{ id: 'assistant-msg' }],
    }),
    getMessageReplies: vi.fn().mockResolvedValue({ messages: [] }),
    getTurnSegments: vi.fn().mockResolvedValue([]),
    getChatElicitations: vi.fn().mockResolvedValue([]),
    ...unique,
  } as unknown as UniqueInternalClient;
  const contexts = {
    findOwned: vi.fn().mockResolvedValue({ id: 'ctx_1', chatId: null }),
    attachChat: vi.fn(),
    attachMessages: vi.fn(),
    findTask: vi.fn(),
  };
  const executor = new InboundAgentExecutor(
    contexts as unknown as ContextRepository,
    new NativeRunObserver(
      { subscribe: vi.fn().mockReturnValue(() => undefined) } as unknown as ChatEventConsumer,
      client,
      { streamTimeoutMs: 1_000 } as GatewayConfig,
    ),
    {
      findById: vi.fn().mockResolvedValue({ enabled: true, assistantId: 'assistant-1' }),
    } as unknown as PublicationRepository,
    { save: vi.fn(), heartbeat: vi.fn() } as unknown as PgTaskStore,
    client,
  );
  return {
    executor,
    contexts,
    bus: { publish: (event: AgentEvent) => events.push(event) },
    events,
  };
}

describe('InboundAgentExecutor', () => {
  it('completes a run that finished before the event subscription existed', async () => {
    const { executor, bus, events } = subject({
      getMessage: vi.fn().mockResolvedValue({
        id: 'assistant-msg',
        text: 'Answer',
        completedAt: '2026-09-30T00:00:00.000Z',
      }),
    });

    await executor.execute(request, bus as never);

    expect(JSON.stringify(events)).toContain('Answer');
    expect(events.at(-1)).toMatchObject({
      data: { status: { state: TaskState.TASK_STATE_COMPLETED } },
    });
  });

  it('fails the task with a generic message instead of internal error details', async () => {
    const { executor, bus, events } = subject({
      getMessage: vi.fn().mockRejectedValue(new Error('node-chat returned 500 for chat-1')),
    });

    await executor.execute(request, bus as never);

    expect(events.at(-1)).toMatchObject({
      data: { status: { state: TaskState.TASK_STATE_FAILED } },
    });
    expect(JSON.stringify(events)).not.toContain('node-chat');
  });

  it('reports a native error as failed and a user stop as canceled', async () => {
    const failed = subject({
      getMessage: vi.fn().mockResolvedValue({
        id: 'assistant-msg',
        text: 'error',
        stoppedStreamingAt: '2026-09-30T00:00:00.000Z',
      }),
    });
    await failed.executor.execute(request, failed.bus as never);
    expect(failed.events.at(-1)).toMatchObject({
      data: { status: { state: TaskState.TASK_STATE_FAILED } },
    });

    const canceled = subject({
      getMessage: vi.fn().mockResolvedValue({
        id: 'assistant-msg',
        stoppedStreamingAt: '2026-09-30T00:00:00.000Z',
        userAbortedAt: '2026-09-30T00:00:00.000Z',
      }),
    });
    await canceled.executor.execute(request, canceled.bus as never);
    expect(canceled.events.at(-1)).toMatchObject({
      data: { status: { state: TaskState.TASK_STATE_CANCELED } },
    });
  });

  it('marks a task canceled only when core confirms the stop', async () => {
    const stopMessage = vi
      .fn()
      .mockResolvedValue({ id: 'assistant-msg', stoppedStreamingAt: null });
    const { executor, contexts, bus, events } = subject({ stopMessage });
    contexts.findTask.mockResolvedValue({
      companyId: 'company-1',
      userId: 'user-1',
      contextId: 'ctx_1',
      chatId: 'chat-1',
      userMessageId: 'user-msg',
      assistantMessageId: 'assistant-msg',
    });

    await expect(executor.cancelTask('task_1', bus as never)).rejects.toMatchObject({
      name: 'TaskNotCancelableError',
    });
    expect(events).toHaveLength(0);

    stopMessage.mockResolvedValue({ id: 'assistant-msg', stoppedStreamingAt: 'now' });
    await executor.cancelTask('task_1', bus as never);
    expect(events.at(-1)).toMatchObject({
      data: { status: { state: TaskState.TASK_STATE_CANCELED } },
    });
  });
});
