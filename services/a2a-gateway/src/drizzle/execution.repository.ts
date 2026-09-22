import { ConflictException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';

import { DRIZZLE, type GatewayDatabase } from './drizzle.module.js';
import type { TenantPrincipal } from './repository.types.js';
import { executions } from './schema/executions.table.js';
import { remoteContexts } from './schema/remote-contexts.table.js';

export interface ExecutionWrite {
  connectionId: string;
  assistantId: string;
  chatId: string;
  userMessageId: string;
  assistantMessageId: string;
  correlation?: Record<string, unknown>;
}

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
