import { ConflictException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import { and, eq, inArray, isNull, sql } from 'drizzle-orm';
import { DRIZZLE, type GatewayDatabase } from './drizzle.module.js';
import type { TenantPrincipal } from './repository.types.js';
import { executions } from './schema/executions.table.js';
import { remoteContexts } from './schema/remote-contexts.table.js';

export const ACTIVE_EXECUTION_STATES = [
  'submitted',
  'sending',
  'working',
  'input-required',
  'auth-required',
];

export const TERMINAL_EXECUTION_STATES = ['completed', 'failed', 'canceled', 'rejected', 'unknown'];

export type ExecutionState =
  | 'submitted'
  | 'sending'
  | 'working'
  | 'input-required'
  | 'auth-required'
  | 'completed'
  | 'failed'
  | 'canceled'
  | 'rejected'
  | 'unknown';

export interface ExecutionWrite {
  connectionId: string;
  assistantId: string;
  chatId: string;
  userMessageId: string;
  assistantMessageId: string;
  correlation?: Record<string, unknown>;
}

export type Execution = typeof executions.$inferSelect;

@Injectable()
export class ExecutionRepository {
  public constructor(@Inject(DRIZZLE) private readonly database: GatewayDatabase) {}

  public async createIdempotent(principal: TenantPrincipal, input: ExecutionWrite, expiresAt: Date) {
    const [created] = await this.database
      .insert(executions)
      .values({
        ...input,
        companyId: principal.companyId,
        userId: principal.userId,
        state: 'submitted',
        expiresAt,
      })
      .onConflictDoNothing({ target: [executions.companyId, executions.userMessageId] })
      .returning();
    if (created) {
      return created;
    }
    const existing = await this.database.query.executions.findFirst({
      where: and(
        eq(executions.companyId, principal.companyId),
        eq(executions.userMessageId, input.userMessageId),
      ),
    });
    if (!existing || existing.userId !== principal.userId) {
      throw new ConflictException('execution idempotency key belongs to another principal');
    }
    return existing;
  }

  public async findOwned(principal: TenantPrincipal, executionId: string) {
    const execution = await this.database.query.executions.findFirst({
      where: and(
        eq(executions.id, executionId),
        eq(executions.companyId, principal.companyId),
        eq(executions.userId, principal.userId),
      ),
    });
    if (!execution) {
      throw new NotFoundException('execution not found');
    }
    return execution;
  }

  /**
   * Moves an execution only out of an active state, so a terminal outcome can never be
   * overwritten by a late event, a retry or a concurrent worker.
   */
  public async transition(
    principal: TenantPrincipal,
    executionId: string,
    state: ExecutionState,
    patch: Partial<Pick<Execution, 'remoteTaskId' | 'elicitationId' | 'lastError' | 'deadlineAt'>> = {},
  ): Promise<Execution | undefined> {
    const terminal = TERMINAL_EXECUTION_STATES.includes(state);
    const [updated] = await this.database
      .update(executions)
      .set({
        ...patch,
        state,
        updatedAt: new Date(),
        ...(terminal ? { finishedAt: new Date() } : {}),
      })
      .where(
        and(
          eq(executions.id, executionId),
          eq(executions.companyId, principal.companyId),
          eq(executions.userId, principal.userId),
          inArray(executions.state, ACTIVE_EXECUTION_STATES),
        ),
      )
      .returning();
    return updated;
  }

  public async requestCancel(companyId: string, executionId: string): Promise<boolean> {
    const [updated] = await this.database
      .update(executions)
      .set({ cancelRequestedAt: new Date(), updatedAt: new Date() })
      .where(
        and(
          eq(executions.id, executionId),
          eq(executions.companyId, companyId),
          inArray(executions.state, ACTIVE_EXECUTION_STATES),
          isNull(executions.cancelRequestedAt),
        ),
      )
      .returning({ id: executions.id });
    return updated !== undefined;
  }

  /** Active executions answering a message, or delegated from it by a parent agent turn. */
  public async findActiveForMessage(companyId: string, messageId: string) {
    return this.database.query.executions.findMany({
      columns: { id: true, companyId: true },
      where: and(
        eq(executions.companyId, companyId),
        inArray(executions.state, ACTIVE_EXECUTION_STATES),
        sql`(${executions.assistantMessageId} = ${messageId} or ${executions.correlation} ->> 'parentMessageId' = ${messageId})`,
      ),
    });
  }

  public async findRemoteContext(companyId: string, connectionId: string, chatId: string) {
    return this.database.query.remoteContexts.findFirst({
      where: and(
        eq(remoteContexts.companyId, companyId),
        eq(remoteContexts.connectionId, connectionId),
        eq(remoteContexts.chatId, chatId),
      ),
    });
  }

  public async saveRemoteContext(
    companyId: string,
    connectionId: string,
    chatId: string,
    remoteContextId: string,
  ) {
    const [created] = await this.database
      .insert(remoteContexts)
      .values({ companyId, connectionId, chatId, remoteContextId })
      .onConflictDoNothing({ target: [remoteContexts.companyId, remoteContexts.chatId] })
      .returning();
    if (created) {
      return created;
    }
    const existing = await this.database.query.remoteContexts.findFirst({
      where: and(eq(remoteContexts.companyId, companyId), eq(remoteContexts.chatId, chatId)),
    });
    if (!existing) {
      throw new NotFoundException('remote context not found');
    }
    return existing;
  }
}
