import {
  ConflictException,
  ForbiddenException,
  HttpException,
  HttpStatus,
  Inject,
  Injectable,
  Logger,
  NotFoundException,
} from '@nestjs/common';
import type { JsonObject } from 'absurd-sdk';
import { z } from 'zod';
import { AuthorizationService } from '../auth/authorization.service.js';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { ConnectionRepository } from '../drizzle/connection.repository.js';
import { ExecutionRepository } from '../drizzle/execution.repository.js';
import { isUniqueViolation } from '../drizzle/unique-violation.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { UniqueInternalError } from '../unique/unique-internal.error.js';
import { WorkflowService } from '../workflow/workflow.service.js';

export const OUTBOUND_RUN_TASK = 'outbound.run';

export const OUTBOUND_RUN_OPTIONS = {
  maxAttempts: 5,
  retryStrategy: { kind: 'exponential' as const, baseSeconds: 2, maxSeconds: 60 },
};

const id = z.string().min(1).max(200);

export const executionRequest = z
  .object({
    assistantId: id,
    chatId: id,
    userMessageId: id,
    assistantMessageId: id,
    // The runner re-reads the turn from core; the text is accepted for compatibility only.
    text: z.string().optional(),
    correlation: z
      .object({ parentMessageId: id.optional(), parentChatId: id, parentAssistantId: id })
      .strict()
      .optional(),
    fileIds: z.array(id).max(100).optional(),
  })
  .strict();

export type ExecutionRequest = z.infer<typeof executionRequest>;

export interface OutboundRunParams extends JsonObject {
  executionId: string;
  companyId: string;
  userId: string;
}

const externalAssistant = z.object({
  id: z.string(),
  executionProvider: z.literal('A2A'),
  a2aConnectionId: z.string().min(1),
});

@Injectable()
export class OutboundExecutionService {
  private readonly logger = new Logger(OutboundExecutionService.name);

  public constructor(
    private readonly authorization: AuthorizationService,
    private readonly connections: ConnectionRepository,
    private readonly executions: ExecutionRepository,
    private readonly unique: UniqueInternalClient,
    private readonly workflow: WorkflowService,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  /**
   * Accepts a turn of an external space. The execution row is the idempotency key (one per user
   * message) and is persisted before the durable run is spawned, so a retried dispatch never
   * starts a second remote run.
   */
  public async start(identity: RequestIdentity, request: ExecutionRequest) {
    await this.authorization.assertNewUse(identity);
    const assistant = externalAssistant.safeParse(
      await this.unique.getAssistant(identity, request.assistantId),
    );
    if (!assistant.success || assistant.data.id !== request.assistantId) {
      throw new ForbiddenException('an external space you may use is required');
    }
    try {
      await this.unique.getMessage(identity, request.chatId, request.assistantMessageId);
    } catch (error) {
      if (error instanceof UniqueInternalError && error.code === 'NOT_FOUND') {
        throw new ForbiddenException('the assistant message does not belong to the caller');
      }
      throw error;
    }
    const connectionId = assistant.data.a2aConnectionId;
    const connection = await this.connections.find(identity.companyId, connectionId);
    if (!connection) {
      throw new NotFoundException('connection not found');
    }
    if (
      connection.disabledAt ||
      !connection.lastVerifiedAt ||
      connection.lastError ||
      connection.assistantId !== request.assistantId
    ) {
      throw new ConflictException('connection is disabled or not verified');
    }
    const expiresAt = new Date(Date.now() + this.config.executionRetentionDays * 86_400_000);
    const execution = await this.createExecution(
      identity,
      {
        connectionId,
        assistantId: request.assistantId,
        chatId: request.chatId,
        userMessageId: request.userMessageId,
        assistantMessageId: request.assistantMessageId,
        correlation: {
          ...(request.correlation ?? {}),
          ...(request.fileIds ? { fileIds: request.fileIds } : {}),
        },
      },
      expiresAt,
    );
    const params: OutboundRunParams = {
      executionId: execution.id,
      companyId: identity.companyId,
      userId: identity.userId,
    };
    const { taskID } = await this.workflow.spawn(OUTBOUND_RUN_TASK, params, {
      ...OUTBOUND_RUN_OPTIONS,
      idempotencyKey: execution.id,
    });
    await this.executions.setWorkflowTask(identity.companyId, execution.id, taskID);
    this.logger.log({
      action: 'execution.start',
      companyId: identity.companyId,
      userId: identity.userId,
      executionId: execution.id,
      connectionId,
      assistantId: request.assistantId,
    });
    return { executionId: execution.id };
  }

  private async createExecution(...args: Parameters<ExecutionRepository['createIdempotent']>) {
    try {
      return await this.executions.createIdempotent(...args);
    } catch (error) {
      if (isUniqueViolation(error, 'a2a_executions_one_active_per_chat_unique')) {
        throw new HttpException(
          'the external agent is still working on the previous message',
          HttpStatus.TOO_MANY_REQUESTS,
        );
      }
      throw error;
    }
  }
}
