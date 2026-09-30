import { Inject, Injectable } from '@nestjs/common';
import { and, count, eq, gte, inArray, lt, notInArray, sql } from 'drizzle-orm';
import { DRIZZLE, type GatewayDatabase } from './drizzle.module.js';
import { ACTIVE_EXECUTION_STATES } from './execution.repository.js';
import { contexts } from './schema/contexts.table.js';
import { executions } from './schema/executions.table.js';
import { tasks } from './schema/tasks.table.js';

const TERMINAL_TASK_STATES = ['3', '4', '5', '7'];

/** Counts for quotas and aggregates for usage attribution; no content is read. */
@Injectable()
export class UsageRepository {
  public constructor(@Inject(DRIZZLE) private readonly database: GatewayDatabase) {}

  public async activeExecutions(companyId: string, connectionId?: string): Promise<number> {
    const [row] = await this.database
      .select({ value: count() })
      .from(executions)
      .where(
        and(
          eq(executions.companyId, companyId),
          inArray(executions.state, ACTIVE_EXECUTION_STATES),
          ...(connectionId ? [eq(executions.connectionId, connectionId)] : []),
        ),
      );
    return row?.value ?? 0;
  }

  public async activeTasks(companyId: string): Promise<number> {
    const [row] = await this.database
      .select({ value: count() })
      .from(tasks)
      .where(and(eq(tasks.companyId, companyId), notInArray(tasks.state, TERMINAL_TASK_STATES)));
    return row?.value ?? 0;
  }

  public async outbound(companyId: string, from: Date, to: Date) {
    return this.database
      .select({
        assistantId: executions.assistantId,
        connectionId: executions.connectionId,
        state: executions.state,
        runs: count(),
        users: sql<number>`count(distinct ${executions.userId})::int`,
        durationSeconds: sql<number>`coalesce(sum(extract(epoch from (${executions.finishedAt} - ${executions.createdAt}))), 0)::float`,
        bytesIn: sql<number>`coalesce(sum(${executions.bytesIn}), 0)::float8`,
        bytesOut: sql<number>`coalesce(sum(${executions.bytesOut}), 0)::float8`,
      })
      .from(executions)
      .where(
        and(
          eq(executions.companyId, companyId),
          gte(executions.createdAt, from),
          lt(executions.createdAt, to),
        ),
      )
      .groupBy(executions.assistantId, executions.connectionId, executions.state);
  }

  public async inbound(companyId: string, from: Date, to: Date) {
    return this.database
      .select({
        publicationId: contexts.publicationId,
        clientId: tasks.clientId,
        state: tasks.state,
        runs: count(),
        users: sql<number>`count(distinct ${tasks.userId})::int`,
        durationSeconds: sql<number>`coalesce(sum(extract(epoch from (${tasks.statusTimestamp} - ${tasks.createdAt}))), 0)::float`,
        bytesIn: sql<number>`coalesce(sum(${tasks.bytesIn}), 0)::float8`,
        bytesOut: sql<number>`coalesce(sum(${tasks.bytesOut}), 0)::float8`,
      })
      .from(tasks)
      .innerJoin(contexts, and(eq(contexts.companyId, tasks.companyId), eq(contexts.id, tasks.contextId)))
      .where(and(eq(tasks.companyId, companyId), gte(tasks.createdAt, from), lt(tasks.createdAt, to)))
      .groupBy(contexts.publicationId, tasks.clientId, tasks.state);
  }

  /** Active and stuck runs per tenant and direction, for gauges and alerts. */
  public async runHealth(stuckBefore: Date) {
    const outbound = await this.database
      .select({
        companyId: executions.companyId,
        active: count(),
        stuck: sql<number>`count(*) filter (where ${executions.updatedAt} < ${stuckBefore})::int`,
      })
      .from(executions)
      .where(inArray(executions.state, ACTIVE_EXECUTION_STATES))
      .groupBy(executions.companyId);
    const inbound = await this.database
      .select({
        companyId: tasks.companyId,
        active: count(),
        stuck: sql<number>`count(*) filter (where coalesce(${tasks.heartbeatAt}, ${tasks.updatedAt}) < ${stuckBefore})::int`,
      })
      .from(tasks)
      .where(notInArray(tasks.state, TERMINAL_TASK_STATES))
      .groupBy(tasks.companyId);
    return [
      ...outbound.map((row) => ({ ...row, direction: 'outbound' as const })),
      ...inbound.map((row) => ({ ...row, direction: 'inbound' as const })),
    ];
  }
}
