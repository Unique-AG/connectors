import type { ListTasksRequest, ListTasksResponse, Task } from '@a2a-js/sdk';
import type { ServerCallContext, TaskStore } from '@a2a-js/sdk/server';
import { Inject, Injectable, UnauthorizedException } from '@nestjs/common';
import { and, count, desc, eq, gte, lt, or, type SQL } from 'drizzle-orm';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { DRIZZLE, type GatewayDatabase } from '../drizzle/drizzle.module.js';
import { tasks } from '../drizzle/schema/tasks.table.js';

interface PageCursor {
  timestamp: string;
  id: string;
}

function identity(context: ServerCallContext): {
  companyId: string;
  userId: string;
  clientId: string;
} {
  const companyId = context.tenant;
  const userId = context.user?.isAuthenticated ? context.user.userName : undefined;
  const headers = context.state.get('headers');
  const clientId =
    typeof headers === 'object' && headers !== null && 'x-client-id' in headers
      ? Reflect.get(headers, 'x-client-id')
      : undefined;
  if (!companyId || !userId) {
    throw new UnauthorizedException('authenticated tenant and user required');
  }
  return { companyId, userId, clientId: typeof clientId === 'string' ? clientId : 'unknown' };
}

function decodeCursor(token: string): PageCursor | undefined {
  if (!token) {
    return undefined;
  }
  try {
    const parsed: unknown = JSON.parse(Buffer.from(token, 'base64url').toString());
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      typeof Reflect.get(parsed, 'timestamp') === 'string' &&
      typeof Reflect.get(parsed, 'id') === 'string'
    ) {
      return parsed as PageCursor;
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function encodeCursor(timestamp: Date, id: string): string {
  return Buffer.from(JSON.stringify({ timestamp: timestamp.toISOString(), id })).toString(
    'base64url',
  );
}

function projectTask(task: Task, params: ListTasksRequest): Task {
  const historyLength = params.historyLength;
  return {
    ...task,
    artifacts: params.includeArtifacts ? task.artifacts : [],
    history:
      historyLength === undefined ? task.history : task.history.slice(Math.max(0, -historyLength)),
  };
}

@Injectable()
export class PgTaskStore implements TaskStore {
  public constructor(
    @Inject(DRIZZLE) private readonly database: GatewayDatabase,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public async save(task: Task, context: ServerCallContext): Promise<void> {
    const owner = identity(context);
    const statusTimestamp = new Date(task.status?.timestamp ?? Date.now());
    const expiresAt = new Date(statusTimestamp);
    expiresAt.setUTCDate(expiresAt.getUTCDate() + this.config.taskRetentionDays);
    const userMessageId = task.history.at(0)?.messageId ?? task.id;

    const [saved] = await this.database
      .insert(tasks)
      .values({
        id: task.id,
        companyId: owner.companyId,
        userId: owner.userId,
        clientId: owner.clientId,
        contextId: task.contextId,
        state: String(task.status?.state ?? 0),
        userMessageId,
        taskSnapshot: task as unknown as Record<string, unknown>,
        statusTimestamp,
        expiresAt,
      })
      .onConflictDoUpdate({
        target: tasks.id,
        set: {
          state: String(task.status?.state ?? 0),
          taskSnapshot: task as unknown as Record<string, unknown>,
          statusTimestamp,
          expiresAt,
          updatedAt: new Date(),
        },
        setWhere: and(eq(tasks.companyId, owner.companyId), eq(tasks.userId, owner.userId)),
      })
      .returning({ id: tasks.id });
    if (!saved) {
      throw new UnauthorizedException('task belongs to another tenant or user');
    }
  }

  public async load(taskId: string, context: ServerCallContext): Promise<Task | undefined> {
    const owner = identity(context);
    const row = await this.database.query.tasks.findFirst({
      columns: { taskSnapshot: true },
      where: and(
        eq(tasks.id, taskId),
        eq(tasks.companyId, owner.companyId),
        eq(tasks.userId, owner.userId),
      ),
    });
    return row?.taskSnapshot as Task | undefined;
  }

  public async list(
    params: ListTasksRequest,
    context: ServerCallContext,
  ): Promise<ListTasksResponse> {
    const owner = identity(context);
    const pageSize = Math.min(100, Math.max(1, params.pageSize ?? 50));
    const filters: SQL[] = [eq(tasks.companyId, owner.companyId), eq(tasks.userId, owner.userId)];
    if (params.contextId) {
      filters.push(eq(tasks.contextId, params.contextId));
    }
    if (params.status) {
      filters.push(eq(tasks.state, String(params.status)));
    }
    if (params.statusTimestampAfter) {
      filters.push(gte(tasks.statusTimestamp, new Date(params.statusTimestampAfter)));
    }
    const unpaginatedWhere = and(...filters);
    const cursor = decodeCursor(params.pageToken);
    if (cursor) {
      const timestamp = new Date(cursor.timestamp);
      filters.push(
        or(
          lt(tasks.statusTimestamp, timestamp),
          and(eq(tasks.statusTimestamp, timestamp), lt(tasks.id, cursor.id)),
        ) as SQL,
      );
    }
    const where = and(...filters);
    const [rows, totalResult] = await Promise.all([
      this.database
        .select({ id: tasks.id, snapshot: tasks.taskSnapshot, timestamp: tasks.statusTimestamp })
        .from(tasks)
        .where(where)
        .orderBy(desc(tasks.statusTimestamp), desc(tasks.id))
        .limit(pageSize + 1),
      this.database.select({ value: count() }).from(tasks).where(unpaginatedWhere),
    ]);
    const hasNext = rows.length > pageSize;
    const page = rows.slice(0, pageSize);
    const last = page.at(-1);
    return {
      tasks: page.map((row) => projectTask(row.snapshot as unknown as Task, params)),
      nextPageToken: hasNext && last ? encodeCursor(last.timestamp, last.id) : '',
      pageSize,
      totalSize: totalResult[0]?.value ?? 0,
    };
  }
}
