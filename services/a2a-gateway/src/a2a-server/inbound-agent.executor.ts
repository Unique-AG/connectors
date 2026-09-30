import assert from 'node:assert';
import { Role, type Task, TaskState, type TaskStatus } from '@a2a-js/sdk';
import {
  AgentEvent,
  type AgentExecutor,
  type ExecutionEventBus,
  type RequestContext,
} from '@a2a-js/sdk/server';
import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { z } from 'zod';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { ContextRepository } from '../drizzle/context.repository.js';
import { PublicationRepository } from '../drizzle/publication.repository.js';
import { ChatEventConsumer } from '../event-bus/chat-event.consumer.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { UniqueInternalError } from '../unique/unique-internal.error.js';
import { awaitsInput, callIdentity, callPublicationId, messageText } from './call-context.js';
import { PgTaskStore } from './pg-task.store.js';

const createdMessageSchema = z.object({
  id: z.string().min(1),
  chatId: z.string().min(1),
  messages: z.array(z.object({ id: z.string().min(1) })).min(1),
});
const completedMessageSchema = z.object({
  id: z.string(),
  text: z.string().nullish(),
  completedAt: z.string().nullish(),
  stoppedStreamingAt: z.string().nullish(),
});
const elicitationSchema = z.object({
  mode: z.enum(['FORM', 'URL']),
  schema: z.unknown().optional(),
  url: z.string().optional(),
});

type ExecutionOutcome =
  | { kind: 'completed'; message: z.infer<typeof completedMessageSchema> }
  | { kind: 'elicitation'; elicitation: z.infer<typeof elicitationSchema> };

function status(state: TaskState): TaskStatus {
  return { state, message: undefined, timestamp: new Date().toISOString() };
}

function failedStatus(request: RequestContext): TaskStatus {
  return {
    ...status(TaskState.TASK_STATE_FAILED),
    message: {
      messageId: `failure-${request.taskId}`,
      contextId: request.contextId,
      taskId: request.taskId,
      role: Role.ROLE_AGENT,
      parts: [
        {
          content: { $case: 'text', value: 'The space could not complete this request.' },
          metadata: undefined,
          filename: '',
          mediaType: 'text/plain',
        },
      ],
      metadata: undefined,
      extensions: [],
      referenceTaskIds: [],
    },
  };
}

@Injectable()
export class InboundAgentExecutor implements AgentExecutor {
  private readonly logger = new Logger(InboundAgentExecutor.name);

  public constructor(
    private readonly contexts: ContextRepository,
    private readonly events: ChatEventConsumer,
    private readonly publications: PublicationRepository,
    private readonly taskStore: PgTaskStore,
    private readonly unique: UniqueInternalClient,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public async execute(request: RequestContext, eventBus: ExecutionEventBus): Promise<void> {
    const current = request.task;
    assert.ok(current, 'task was not admitted');
    try {
      const identity = callIdentity(request.context);
      const outcome = awaitsInput(current)
        ? await this.resume(request, current, identity, eventBus)
        : await this.start(request, current, identity, eventBus);
      this.publishOutcome(request, eventBus, outcome);
    } catch (error) {
      this.logger.error({ msg: 'native execution failed', taskId: request.taskId, err: error });
      const failed: Task = { ...current, status: failedStatus(request) };
      eventBus.publish(AgentEvent.task(failed));
      eventBus.publish(
        AgentEvent.statusUpdate({
          taskId: request.taskId,
          contextId: request.contextId,
          status: failed.status,
          metadata: undefined,
        }),
      );
    }
  }

  public async cancelTask(taskId: string, eventBus: ExecutionEventBus): Promise<void> {
    const storedTask = await this.contexts.findTask(taskId);
    if (!storedTask?.assistantMessageId || !storedTask.chatId) {
      throw new NotFoundException('task not found');
    }
    await this.unique.stopMessage(
      { companyId: storedTask.companyId, userId: storedTask.userId, roles: [] },
      storedTask.chatId,
      storedTask.assistantMessageId,
    );
    eventBus.publish(
      AgentEvent.statusUpdate({
        taskId,
        contextId: storedTask.contextId,
        status: status(TaskState.TASK_STATE_CANCELED),
        metadata: undefined,
      }),
    );
  }

  private async start(
    request: RequestContext,
    current: Task,
    identity: RequestIdentity,
    eventBus: ExecutionEventBus,
  ): Promise<ExecutionOutcome> {
    const publicationId = callPublicationId(request.context);
    const publication = await this.publications.findById(identity.companyId, publicationId);
    const context = await this.contexts.findOwned(identity, publicationId, request.contextId);
    if (!publication?.enabled || !context) {
      throw new NotFoundException('publication not found');
    }
    const created = createdMessageSchema.parse(
      await this.unique.createMessage(
        identity,
        publication.assistantId,
        context.chatId ?? undefined,
        messageText(request.userMessage),
      ),
    );
    if (!context.chatId) {
      await this.contexts.attachChat(identity, request.contextId, created.chatId);
    }
    const assistantMessageId = created.messages[0]?.id;
    assert.ok(assistantMessageId, 'assistant message was not created');
    const working: Task = { ...current, status: status(TaskState.TASK_STATE_WORKING) };
    await this.taskStore.save(working, request.context);
    await this.contexts.attachMessages(identity, request.taskId, created.id, assistantMessageId);
    eventBus.publish(AgentEvent.task(working));
    return this.waitForOutcome(identity, created.chatId, assistantMessageId);
  }

  private async resume(
    request: RequestContext,
    current: Task,
    identity: RequestIdentity,
    eventBus: ExecutionEventBus,
  ): Promise<ExecutionOutcome> {
    const storedTask = await this.contexts.findTask(request.taskId);
    if (!storedTask?.assistantMessageId || !storedTask.chatId) {
      throw new NotFoundException('task not found');
    }
    const elicitation = z
      .object({ id: z.string().min(1) })
      .parse(await this.unique.getPendingElicitation(identity, storedTask.assistantMessageId));
    await this.unique.respondToElicitation(
      identity,
      elicitation.id,
      'ACCEPT',
      messageText(request.userMessage),
    );
    eventBus.publish(AgentEvent.task({ ...current, status: status(TaskState.TASK_STATE_WORKING) }));
    return this.waitForOutcome(identity, storedTask.chatId, storedTask.assistantMessageId);
  }

  private publishOutcome(
    request: RequestContext,
    eventBus: ExecutionEventBus,
    outcome: ExecutionOutcome,
  ): void {
    if (outcome.kind === 'elicitation') {
      const elicitation = outcome.elicitation;
      const part =
        elicitation.mode === 'FORM'
          ? {
              content: { $case: 'data' as const, value: elicitation.schema ?? {} },
              metadata: undefined,
              filename: '',
              mediaType: 'application/json',
            }
          : {
              content: { $case: 'text' as const, value: elicitation.url ?? '' },
              metadata: undefined,
              filename: '',
              mediaType: 'text/plain',
            };
      eventBus.publish(
        AgentEvent.statusUpdate({
          taskId: request.taskId,
          contextId: request.contextId,
          status: {
            ...status(
              elicitation.mode === 'FORM'
                ? TaskState.TASK_STATE_INPUT_REQUIRED
                : TaskState.TASK_STATE_AUTH_REQUIRED,
            ),
            message: {
              messageId: `elicitation-${request.taskId}`,
              contextId: request.contextId,
              taskId: request.taskId,
              role: Role.ROLE_AGENT,
              parts: [part],
              metadata: undefined,
              extensions: [],
              referenceTaskIds: [],
            },
          },
          metadata: undefined,
        }),
      );
      return;
    }
    const completed = outcome.message;
    const terminalState = completed.stoppedStreamingAt
      ? TaskState.TASK_STATE_CANCELED
      : TaskState.TASK_STATE_COMPLETED;
    if (completed.text) {
      eventBus.publish(
        AgentEvent.artifactUpdate({
          taskId: request.taskId,
          contextId: request.contextId,
          artifact: {
            artifactId: `text-${request.taskId}`,
            name: 'Response',
            description: '',
            parts: [
              {
                content: { $case: 'text', value: completed.text },
                metadata: undefined,
                filename: '',
                mediaType: 'text/plain',
              },
            ],
            metadata: undefined,
            extensions: [],
          },
          append: false,
          lastChunk: true,
          metadata: undefined,
        }),
      );
    }
    eventBus.publish(
      AgentEvent.statusUpdate({
        taskId: request.taskId,
        contextId: request.contextId,
        status: status(terminalState),
        metadata: undefined,
      }),
    );
  }

  private waitForOutcome(
    identity: RequestIdentity,
    chatId: string,
    assistantMessageId: string,
  ): Promise<ExecutionOutcome> {
    return new Promise((resolve, reject) => {
      let settled = false;
      const settle = (outcome: () => Promise<ExecutionOutcome | undefined>): void => {
        outcome().then(
          (result) => {
            if (result && !settled) {
              settled = true;
              cleanup();
              resolve(result);
            }
          },
          (error: unknown) => {
            if (!settled) {
              settled = true;
              cleanup();
              reject(error);
            }
          },
        );
      };
      const unsubscribe = this.events.subscribe(identity.companyId, assistantMessageId, (event) => {
        if (event.type === 'unique.chat.elicitation.created') {
          settle(async () => ({
            kind: 'elicitation',
            elicitation: elicitationSchema.parse(event.payload),
          }));
        } else if (event.type === 'unique.chat.assistant-message.finished') {
          settle(async () => ({
            kind: 'completed',
            message: completedMessageSchema.parse(
              await this.unique.getMessage(identity, chatId, assistantMessageId),
            ),
          }));
        }
      });
      const timer = setTimeout(() => {
        settle(() => Promise.reject(new Error('native execution timed out')));
      }, this.config.streamTimeoutMs);
      const cleanup = (): void => {
        unsubscribe();
        clearTimeout(timer);
      };
      // The run may already have finished or paused before the subscription existed.
      settle(() => this.currentOutcome(identity, chatId, assistantMessageId));
    });
  }

  private async currentOutcome(
    identity: RequestIdentity,
    chatId: string,
    assistantMessageId: string,
  ): Promise<ExecutionOutcome | undefined> {
    const message = completedMessageSchema.parse(
      await this.unique.getMessage(identity, chatId, assistantMessageId),
    );
    if (message.completedAt || message.stoppedStreamingAt) {
      return { kind: 'completed', message };
    }
    try {
      return {
        kind: 'elicitation',
        elicitation: elicitationSchema.parse(
          await this.unique.getPendingElicitation(identity, assistantMessageId),
        ),
      };
    } catch (error) {
      if (error instanceof UniqueInternalError && error.code === 'NOT_FOUND') {
        return undefined;
      }
      throw error;
    }
  }
}
