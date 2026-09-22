import { type Message, Role, type Task, TaskState, type TaskStatus } from '@a2a-js/sdk';
import {
  AgentEvent,
  type AgentExecutor,
  type ExecutionEventBus,
  type RequestContext,
} from '@a2a-js/sdk/server';
import { BadRequestException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import { z } from 'zod';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { ContextRepository } from '../drizzle/context.repository.js';
import { PublicationRepository } from '../drizzle/publication.repository.js';
import { ChatEventConsumer } from '../event-bus/chat-event.consumer.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
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

function requestIdentity(context: RequestContext['context']): RequestIdentity {
  const userId = context.user?.isAuthenticated ? context.user.userName : undefined;
  const roles = context.state.get('roles');
  if (!context.tenant || !userId) {
    throw new NotFoundException('publication not found');
  }
  return {
    companyId: context.tenant,
    userId,
    roles: Array.isArray(roles)
      ? roles.filter((role): role is string => typeof role === 'string')
      : [],
  };
}

function publicationId(context: RequestContext['context']): string {
  const value = context.state.get('publicationId');
  if (typeof value !== 'string' || !value) {
    throw new NotFoundException('publication not found');
  }
  return value;
}

function messageText(message: Message): string {
  const values = message.parts.map((part) => {
    if (part.content?.$case === 'text') {
      return part.content.value;
    }
    if (part.content?.$case === 'data') {
      return `\n\n\`\`\`json\n${JSON.stringify(part.content.value, null, 2)}\n\`\`\``;
    }
    throw new BadRequestException('only text and data message parts are supported');
  });
  const text = values.join('').trim();
  if (!text) {
    throw new BadRequestException('message content is required');
  }
  return text;
}

function status(state: TaskState): TaskStatus {
  return { state, message: undefined, timestamp: new Date().toISOString() };
}

function task(request: RequestContext, state: TaskState): Task {
  return {
    id: request.taskId,
    contextId: request.contextId,
    status: status(state),
    artifacts: [],
    history: [request.userMessage],
    metadata: undefined,
  };
}

@Injectable()
export class InboundAgentExecutor implements AgentExecutor {
  public constructor(
    private readonly authorization: ResourceAuthorizationService,
    private readonly contexts: ContextRepository,
    private readonly events: ChatEventConsumer,
    private readonly publications: PublicationRepository,
    private readonly taskStore: PgTaskStore,
    private readonly unique: UniqueInternalClient,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public async execute(request: RequestContext, eventBus: ExecutionEventBus): Promise<void> {
    const identity = requestIdentity(request.context);
    const currentPublicationId = publicationId(request.context);
    await this.authorization.publication(identity, currentPublicationId, true);
    const publication = await this.publications.findEnabledById(currentPublicationId);
    if (!publication) {
      throw new NotFoundException('publication not found');
    }

    if (request.task) {
      if (
        request.task.status?.state !== TaskState.TASK_STATE_INPUT_REQUIRED &&
        request.task.status?.state !== TaskState.TASK_STATE_AUTH_REQUIRED
      ) {
        throw new BadRequestException('task is terminal; send a new message in the same context');
      }
      const storedTask = await this.contexts.findTask(request.taskId);
      if (!storedTask?.assistantMessageId) {
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
      eventBus.publish(
        AgentEvent.task({
          ...request.task,
          status: status(TaskState.TASK_STATE_WORKING),
          history: [...request.task.history, request.userMessage],
        }),
      );
      const outcome = await this.waitForOutcome(
        identity,
        storedTask.chatId,
        storedTask.assistantMessageId,
      );
      this.publishOutcome(request, eventBus, outcome);
      return;
    }

    const existingContext = await this.contexts.findOwned(
      identity,
      currentPublicationId,
      request.contextId,
    );
    const created = createdMessageSchema.parse(
      await this.unique.createMessage(
        identity,
        publication.assistantId,
        existingContext?.chatId,
        messageText(request.userMessage),
      ),
    );
    if (!existingContext) {
      await this.contexts.create(identity, currentPublicationId, request.contextId, created.chatId);
    }

    const [assistantMessage] = created.messages;
    if (!assistantMessage) {
      throw new Error('assistant message was not created');
    }
    const assistantMessageId = assistantMessage.id;
    const workingTask = task(request, TaskState.TASK_STATE_WORKING);
    await this.taskStore.save(workingTask, request.context);
    await this.contexts.attachMessages(identity, request.taskId, created.id, assistantMessageId);
    eventBus.publish(AgentEvent.task(workingTask));

    const outcome = await this.waitForOutcome(identity, created.chatId, assistantMessageId);
    this.publishOutcome(request, eventBus, outcome);
  }

  public async cancelTask(taskId: string, eventBus: ExecutionEventBus): Promise<void> {
    const storedTask = await this.contexts.findTask(taskId);
    if (!storedTask?.assistantMessageId) {
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

  private async waitForOutcome(
    identity: RequestIdentity,
    chatId: string,
    assistantMessageId: string,
  ): Promise<ExecutionOutcome> {
    const deadline = Date.now() + this.config.streamTimeoutMs;
    return new Promise((resolve, reject) => {
      let timer: NodeJS.Timeout | undefined;
      const unsubscribe = this.events.subscribe(
        identity.companyId,
        assistantMessageId,
        async (event) => {
          if (event.type === 'unique.chat.elicitation.created') {
            const elicitation = elicitationSchema.parse(event.payload);
            cleanup();
            resolve({ kind: 'elicitation', elicitation });
            return;
          }
          if (event.type !== 'unique.chat.assistant-message.finished') {
            return;
          }
          try {
            const message = completedMessageSchema.parse(
              await this.unique.getMessage(identity, chatId, assistantMessageId),
            );
            cleanup();
            resolve({ kind: 'completed', message });
          } catch (error) {
            cleanup();
            reject(error);
          }
        },
      );
      const cleanup = (): void => {
        unsubscribe();
        if (timer) {
          clearTimeout(timer);
        }
      };
      timer = setTimeout(
        () => {
          cleanup();
          reject(new Error('native execution timed out'));
        },
        Math.max(1, deadline - Date.now()),
      );
    });
  }
}
