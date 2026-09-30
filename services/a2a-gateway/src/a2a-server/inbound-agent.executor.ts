import assert from 'node:assert';
import { type Task, TaskState } from '@a2a-js/sdk';
import { TaskNotCancelableError } from '@a2a-js/sdk/errors';
import {
  AgentEvent,
  type AgentExecutor,
  type ExecutionEventBus,
  type RequestContext,
} from '@a2a-js/sdk/server';
import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { z } from 'zod';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { ChatFilesService } from '../bridge/chat-files.service.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { ContextRepository } from '../drizzle/context.repository.js';
import { PublicationRepository } from '../drizzle/publication.repository.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import {
  awaitsInput,
  callIdentity,
  callPublicationId,
  messageContent,
  messageText,
} from './call-context.js';
import {
  failedStatus,
  fileUrlFor,
  outcomeArtifacts,
  outcomeStatus,
  taskStatus,
  textArtifact,
} from './inbound-translation.js';
import { NativeRunObserver, type NativeTurn, type RunOutcome } from './native-run-observer.js';
import { PgTaskStore } from './pg-task.store.js';

const createdMessageSchema = z.object({
  id: z.string().min(1),
  chatId: z.string().min(1),
  messages: z.array(z.object({ id: z.string().min(1) })),
});

const repliesSchema = z.object({ messages: z.array(z.object({ id: z.string().min(1) })) });

const stoppedSchema = z.object({ stoppedStreamingAt: z.string().nullish() });

@Injectable()
export class InboundAgentExecutor implements AgentExecutor {
  private readonly logger = new Logger(InboundAgentExecutor.name);

  public constructor(
    private readonly contexts: ContextRepository,
    private readonly observer: NativeRunObserver,
    private readonly publications: PublicationRepository,
    private readonly taskStore: PgTaskStore,
    private readonly unique: UniqueInternalClient,
    private readonly chatFiles: ChatFilesService,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public async execute(request: RequestContext, eventBus: ExecutionEventBus): Promise<void> {
    const current = request.task;
    assert.ok(current, 'task was not admitted');
    try {
      const identity = callIdentity(request.context);
      const run = awaitsInput(current)
        ? await this.resume(request, current, identity, eventBus)
        : await this.start(request, current, identity, eventBus);
      const outcome = await this.observer.observe({
        identity,
        turn: run,
        onText: (text) => {
          eventBus.publish(
            AgentEvent.artifactUpdate({
              taskId: request.taskId,
              contextId: request.contextId,
              artifact: textArtifact(request.taskId, text),
              append: false,
              lastChunk: false,
              metadata: undefined,
            }),
          );
        },
        onHeartbeat: () => this.taskStore.heartbeat(identity.companyId, request.taskId),
      });
      this.publishOutcome(request, eventBus, outcome);
    } catch (error) {
      this.logger.error({ msg: 'native execution failed', taskId: request.taskId, err: error });
      const failed: Task = { ...current, status: failedStatus(current) };
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

  /** Stops the native turn; the task is canceled only once core confirms the stop. */
  public async cancelTask(taskId: string, eventBus: ExecutionEventBus): Promise<void> {
    const storedTask = await this.contexts.findTask(taskId);
    if (!storedTask?.assistantMessageId || !storedTask.chatId) {
      throw new TaskNotCancelableError('the task has not started a native run');
    }
    const stopped = stoppedSchema.parse(
      await this.unique.stopMessage(
        { companyId: storedTask.companyId, userId: storedTask.userId, roles: [] },
        storedTask.chatId,
        storedTask.assistantMessageId,
      ),
    );
    if (!stopped.stoppedStreamingAt) {
      throw new TaskNotCancelableError('the space did not confirm the cancellation');
    }
    eventBus.publish(
      AgentEvent.statusUpdate({
        taskId,
        contextId: storedTask.contextId,
        status: taskStatus(TaskState.TASK_STATE_CANCELED),
        metadata: undefined,
      }),
    );
  }

  private async start(
    request: RequestContext,
    current: Task,
    identity: RequestIdentity,
    eventBus: ExecutionEventBus,
  ): Promise<NativeTurn> {
    const publicationId = callPublicationId(request.context);
    const publication = await this.publications.findById(identity.companyId, publicationId);
    const context = await this.contexts.findOwned(identity, publicationId, request.contextId);
    if (!publication?.enabled || !context) {
      throw new NotFoundException('publication not found');
    }
    const content = messageContent(request.userMessage, this.config.maxRemoteFileBytes);
    let chatId = context.chatId ?? undefined;
    if (!chatId && content.files.length) {
      // Files are owned by a chat, so the chat has to exist before they are uploaded.
      chatId = z
        .object({ id: z.string() })
        .parse(await this.unique.createChat(identity, publication.assistantId)).id;
      await this.contexts.attachChat(identity, request.contextId, chatId);
    }
    const fileIds: string[] = [];
    for (const file of content.files) {
      fileIds.push(await this.chatFiles.upload(identity, chatId ?? '', file));
    }
    const created = createdMessageSchema.parse(
      await this.unique.createMessage(
        identity,
        publication.assistantId,
        chatId,
        content.text,
        fileIds,
      ),
    );
    if (!chatId) {
      await this.contexts.attachChat(identity, request.contextId, created.chatId);
    }
    // The mutation returns the user message as persisted before its assistant shell.
    const assistantMessageId =
      created.messages[0]?.id ??
      repliesSchema.parse(await this.unique.getMessageReplies(identity, created.chatId, created.id))
        .messages[0]?.id;
    assert.ok(assistantMessageId, 'assistant message was not created');
    await this.contexts.attachMessages(identity, request.taskId, created.id, assistantMessageId);
    const working: Task = { ...current, status: taskStatus(TaskState.TASK_STATE_WORKING) };
    await this.taskStore.save(working, request.context);
    eventBus.publish(AgentEvent.task(working));
    return { chatId: created.chatId, userMessageId: created.id, messageId: assistantMessageId };
  }

  private async resume(
    request: RequestContext,
    current: Task,
    identity: RequestIdentity,
    eventBus: ExecutionEventBus,
  ): Promise<NativeTurn> {
    const storedTask = await this.contexts.findTask(request.taskId);
    if (!storedTask?.assistantMessageId || !storedTask.chatId) {
      throw new NotFoundException('task not found');
    }
    const elicitation = await this.observer.pendingElicitation(identity, storedTask.chatId);
    if (!elicitation) {
      throw new NotFoundException('no pending elicitation');
    }
    await this.unique.respondToElicitation(identity, elicitation.id, 'ACCEPT', {
      answer: messageText(request.userMessage),
    });
    eventBus.publish(
      AgentEvent.task({ ...current, status: taskStatus(TaskState.TASK_STATE_WORKING) }),
    );
    return {
      chatId: storedTask.chatId,
      userMessageId: storedTask.userMessageId,
      messageId: storedTask.assistantMessageId,
    };
  }

  private publishOutcome(
    request: RequestContext,
    eventBus: ExecutionEventBus,
    outcome: RunOutcome,
  ): void {
    const fileUrl = fileUrlFor(
      this.config.publicBaseUrl,
      callPublicationId(request.context),
      request.taskId,
    );
    for (const artifact of outcomeArtifacts(request.taskId, outcome, fileUrl)) {
      eventBus.publish(
        AgentEvent.artifactUpdate({
          taskId: request.taskId,
          contextId: request.contextId,
          artifact,
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
        status: outcomeStatus({ id: request.taskId, contextId: request.contextId }, outcome),
        metadata: undefined,
      }),
    );
  }
}
