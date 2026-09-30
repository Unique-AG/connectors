import { Inject, Injectable } from '@nestjs/common';
import { and, eq, inArray, isNull, lt, notExists, notInArray, sql } from 'drizzle-orm';
import { DRIZZLE, type GatewayDatabase } from './drizzle.module.js';
import { ACTIVE_EXECUTION_STATES } from './execution.repository.js';
import { connections } from './schema/connections.table.js';
import { contexts } from './schema/contexts.table.js';
import { executions } from './schema/executions.table.js';
import { publications } from './schema/publications.table.js';
import { remoteContexts } from './schema/remote-contexts.table.js';
import { tasks } from './schema/tasks.table.js';

const TERMINAL_TASK_STATES = ['3', '4', '5', '7'];

/**
 * Deletes only gateway-owned protocol state. Chats, messages and files belong to core and are
 * never touched. Every purge is bounded so one maintenance tick stays short.
 */
@Injectable()
export class RetentionRepository {
  public constructor(@Inject(DRIZZLE) private readonly database: GatewayDatabase) {}

  /** Expired terminal tasks; artifacts and push configs cascade. */
  public async purgeTasks(now: Date, limit: number): Promise<number> {
    const expired = this.database
      .select({ id: tasks.id })
      .from(tasks)
      .where(and(lt(tasks.expiresAt, now), inArray(tasks.state, TERMINAL_TASK_STATES)))
      .limit(limit);
    const deleted = await this.database
      .delete(tasks)
      .where(inArray(tasks.id, expired))
      .returning({ id: tasks.id });
    return deleted.length;
  }

  /** Contexts that no longer hold tasks and were idle for the retention period. */
  public async purgeContexts(before: Date, limit: number): Promise<number> {
    const idle = this.database
      .select({ id: contexts.id })
      .from(contexts)
      .where(
        and(
          lt(contexts.updatedAt, before),
          notExists(
            this.database
              .select({ id: tasks.id })
              .from(tasks)
              .where(and(eq(tasks.companyId, contexts.companyId), eq(tasks.contextId, contexts.id))),
          ),
        ),
      )
      .limit(limit);
    const deleted = await this.database
      .delete(contexts)
      .where(inArray(contexts.id, idle))
      .returning({ id: contexts.id });
    return deleted.length;
  }

  /** Expired terminal executions (kept until then for usage attribution). */
  public async purgeExecutions(now: Date, limit: number): Promise<number> {
    const expired = this.database
      .select({ id: executions.id })
      .from(executions)
      .where(
        and(lt(executions.expiresAt, now), notInArray(executions.state, ACTIVE_EXECUTION_STATES)),
      )
      .limit(limit);
    const deleted = await this.database
      .delete(executions)
      .where(inArray(executions.id, expired))
      .returning({ id: executions.id });
    return deleted.length;
  }

  /** Chat-to-remote-context mappings without a recent turn. */
  public async purgeRemoteContexts(before: Date, limit: number): Promise<number> {
    const idle = this.database
      .select({ id: remoteContexts.id })
      .from(remoteContexts)
      .where(
        and(
          lt(remoteContexts.updatedAt, before),
          notExists(
            this.database
              .select({ id: executions.id })
              .from(executions)
              .where(
                and(
                  eq(executions.companyId, remoteContexts.companyId),
                  eq(executions.chatId, remoteContexts.chatId),
                ),
              ),
          ),
        ),
      )
      .limit(limit);
    const deleted = await this.database
      .delete(remoteContexts)
      .where(inArray(remoteContexts.id, idle))
      .returning({ id: remoteContexts.id });
    return deleted.length;
  }

  /**
   * Connections no space references (a failed create, a replaced connection) once they are old
   * enough that no save can still be binding them, and without execution history.
   */
  public async purgeUnboundConnections(before: Date, limit: number): Promise<number> {
    const unbound = this.database
      .select({ id: connections.id })
      .from(connections)
      .where(
        and(
          isNull(connections.assistantId),
          lt(connections.updatedAt, before),
          notExists(
            this.database
              .select({ id: executions.id })
              .from(executions)
              .where(
                and(
                  eq(executions.companyId, connections.companyId),
                  eq(executions.connectionId, connections.id),
                ),
              ),
          ),
        ),
      )
      .limit(limit);
    const deleted = await this.database
      .delete(connections)
      .where(inArray(connections.id, unbound))
      .returning({ id: connections.id });
    return deleted.length;
  }

  /** Enabled publications with the id of the admin who configured them, for reconciliation. */
  public async enabledPublications(after: string, limit: number) {
    return this.database
      .select({
        id: publications.id,
        companyId: publications.companyId,
        assistantId: publications.assistantId,
        createdByUserId: publications.createdByUserId,
      })
      .from(publications)
      .where(and(eq(publications.enabled, true), sql`${publications.id} > ${after}`))
      .orderBy(publications.id)
      .limit(limit);
  }
}
