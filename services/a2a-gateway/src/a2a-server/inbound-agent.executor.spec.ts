import { TaskState } from '@a2a-js/sdk';
import { type ExecutionEventBus, type RequestContext, ServerCallContext } from '@a2a-js/sdk/server';
import { describe, expect, it, vi } from 'vitest';
import type { GatewayConfig } from '../config/config.js';
import type { ContextRepository } from '../drizzle/context.repository.js';
import type { PublicationRepository } from '../drizzle/publication.repository.js';
import type { ChatEventConsumer } from '../event-bus/chat-event.consumer.js';
import type { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { InboundAgentExecutor } from './inbound-agent.executor.js';
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
  const executor = new InboundAgentExecutor(
    {
      findOwned: vi.fn().mockResolvedValue({ id: 'ctx_1', chatId: null }),
      attachChat: vi.fn(),
      attachMessages: vi.fn(),
    } as unknown as ContextRepository,
    { subscribe: vi.fn().mockReturnValue(() => undefined) } as unknown as ChatEventConsumer,
    {
      findById: vi.fn().mockResolvedValue({ enabled: true, assistantId: 'assistant-1' }),
    } as unknown as PublicationRepository,
    { save: vi.fn() } as unknown as PgTaskStore,
    {
      createMessage: vi.fn().mockResolvedValue({
        id: 'user-msg',
        chatId: 'chat-1',
        messages: [{ id: 'assistant-msg' }],
      }),
      ...unique,
    } as unknown as UniqueInternalClient,
    { streamTimeoutMs: 1_000 } as GatewayConfig,
  );
  return { executor, bus: { publish: (event: AgentEvent) => events.push(event) }, events };
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
});
