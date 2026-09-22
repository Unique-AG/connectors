import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';

import { DRIZZLE, type GatewayDatabase } from './drizzle.module.js';
import type { TenantPrincipal } from './repository.types.js';
import { contexts } from './schema/contexts.table.js';
import { tasks } from './schema/tasks.table.js';

@Injectable()
export class ContextRepository {
  public constructor(@Inject(DRIZZLE) private readonly database: GatewayDatabase) {}

  public async create(
    principal: TenantPrincipal,
    publicationId: string,
    contextId: string,
    chatId: string,
  ): Promise<void> {
    await this.database.insert(contexts).values({
      id: contextId,
      companyId: principal.companyId,
      userId: principal.userId,
      publicationId,
      chatId,
    });
  }

  public async findOwned(principal: TenantPrincipal, publicationId: string, contextId: string) {
    return this.database.query.contexts.findFirst({
      where: and(
        eq(contexts.id, contextId),
        eq(contexts.companyId, principal.companyId),
        eq(contexts.userId, principal.userId),
        eq(contexts.publicationId, publicationId),
      ),
    });
  }

  public async findTask(taskId: string) {
    const [task] = await this.database
      .select({
        id: tasks.id,
        companyId: tasks.companyId,
        userId: tasks.userId,
        contextId: tasks.contextId,
        assistantMessageId: tasks.assistantMessageId,
        chatId: contexts.chatId,
      })
      .from(tasks)
      .innerJoin(
        contexts,
        and(eq(contexts.companyId, tasks.companyId), eq(contexts.id, tasks.contextId)),
      )
      .where(eq(tasks.id, taskId))
      .limit(1);
    return task;
  }

  public async attachMessages(
    principal: TenantPrincipal,
    taskId: string,
    userMessageId: string,
    assistantMessageId?: string,
  ): Promise<void> {
    await this.database
      .update(tasks)
      .set({ userMessageId, assistantMessageId, updatedAt: new Date() })
      .where(
        and(
          eq(tasks.id, taskId),
          eq(tasks.companyId, principal.companyId),
          eq(tasks.userId, principal.userId),
        ),
      );
  }
}
