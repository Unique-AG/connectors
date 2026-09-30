import { type SendMessageRequest, TaskState } from '@a2a-js/sdk';
import { RequestMalformedError, UnsupportedOperationError } from '@a2a-js/sdk/errors';
import type { ServerCallContext } from '@a2a-js/sdk/server';
import { Injectable } from '@nestjs/common';
import { typeid } from 'typeid-js';
import { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import { ContextRepository } from '../drizzle/context.repository.js';
import { isUniqueViolation } from '../drizzle/unique-violation.js';
import { awaitsInput, callIdentity, callPublicationId, messageText } from './call-context.js';
import { PgTaskStore } from './pg-task.store.js';

function contextBusy(): RequestMalformedError {
  return Object.assign(new RequestMalformedError('a task is already active in this context'), {
    reason: 'CONTEXT_BUSY',
  });
}

/**
 * Validates a send before any native work starts and reserves the task as SUBMITTED, so the
 * one-active-task-per-context index rejects concurrent sends atomically (D-06).
 */
@Injectable()
export class InboundAdmissionService {
  public constructor(
    private readonly authorization: ResourceAuthorizationService,
    private readonly contexts: ContextRepository,
    private readonly taskStore: PgTaskStore,
  ) {}

  public async admit(
    params: SendMessageRequest,
    context: ServerCallContext,
  ): Promise<SendMessageRequest> {
    const message = params.message;
    if (!message?.messageId) {
      throw new RequestMalformedError('message.messageId is required');
    }
    const identity = callIdentity(context);
    const publicationId = callPublicationId(context);
    await this.authorization.publication(identity, publicationId, true);
    messageText(message);

    if (message.taskId) {
      const task = await this.taskStore.load(message.taskId, context);
      if (task && !awaitsInput(task)) {
        throw new UnsupportedOperationError(
          'task is not awaiting input; send a new message in the same context',
        );
      }
      return params;
    }

    const contextId = message.contextId || typeid('ctx').toString();
    if (!message.contextId) {
      await this.contexts.create(identity, publicationId, contextId);
    } else if (!(await this.contexts.findOwned(identity, publicationId, contextId))) {
      throw new RequestMalformedError('unknown contextId');
    }
    const admitted = { ...message, contextId, taskId: typeid('task').toString() };
    try {
      await this.taskStore.save(
        {
          id: admitted.taskId,
          contextId,
          status: {
            state: TaskState.TASK_STATE_SUBMITTED,
            message: undefined,
            timestamp: new Date().toISOString(),
          },
          artifacts: [],
          history: [],
          metadata: undefined,
        },
        context,
      );
    } catch (error) {
      if (isUniqueViolation(error, 'a2a_tasks_one_active_per_context_unique')) {
        throw contextBusy();
      }
      throw error;
    }
    return { ...params, message: admitted };
  }
}
