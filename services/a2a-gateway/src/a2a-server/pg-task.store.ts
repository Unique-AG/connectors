import type { ListTasksRequest, ListTasksResponse, Task } from '@a2a-js/sdk';
import type { ServerCallContext, TaskStore } from '@a2a-js/sdk/server';
import { Inject, Injectable, NotFoundException, UnauthorizedException } from '@nestjs/common';
import {
  and,
  count,
  desc,
  eq,
  gte,
  inArray,
  isNull,
  lt,
  notInArray,
  or,
  type SQL,
  sql,
} from 'drizzle-orm';
import { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { DRIZZLE, type GatewayDatabase } from '../drizzle/drizzle.module.js';
import { contexts } from '../drizzle/schema/contexts.table.js';
import { tasks } from '../drizzle/schema/tasks.table.js';

interface PageCursor {
  timestamp: string;
  id: string;
}

function identity(context: ServerCallContext): {
  companyId: string;
  userId: string;
  clientId: string;
  publicationId: string;
  roles: string[];
} {
  const companyId = context.tenant;
  const userId = context.user?.isAuthenticated ? context.user.userName : undefined;
  const headers = context.state.get('headers');
  const clientId =
    typeof headers === 'object' && headers !== null && 'x-client-id' in headers
      ? Reflect.get(headers, 'x-client-id')
      : undefined;
  const publicationId = context.state.get('publicationId');
  if (
    !companyId ||
    !userId ||
    typeof clientId !== 'string' ||
    !clientId ||
    typeof publicationId !== 'string' ||
    !publicationId
  ) {
    throw new UnauthorizedException('authenticated tenant and user required');
  }
  return { companyId, userId, clientId, publicationId, roles: [] };
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

const TERMINAL_STATES = ['3', '4', '5', '7'];

// Terminal tasks accept only an idempotent re-save of the same state.
function terminalGuard(nextState: string): SQL {
  return or(notInArray(tasks.state, TERMINAL_STATES), eq(tasks.state, nextState)) as SQL;
}

/**
 * File bytes sent by clients already live in the chat; they are not duplicated into the
 * snapshot (and would not survive the JSON round trip as bytes).
 */
function persistable(task: Task): Record<string, unknown> {
  return {
    ...task,
    history: task.history.map((message) => ({
      ...message,
      parts: message.parts.filter((part) => part.content?.$case !== 'raw'),
    })),
  } as unknown as Record<string, unknown>;
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
    private readonly authorization: ResourceAuthorizationService,
  ) {}

  public async save(task: Task, context: ServerCallContext): Promise<void> {
    const owner = identity(context);
    await this.authorization.context(owner, owner.publicationId, task.contextId);
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
        taskSnapshot: persistable(task),
        statusTimestamp,
        expiresAt,
      })
      .onConflictDoUpdate({
        target: tasks.id,
        set: {
          state: String(task.status?.state ?? 0),
          taskSnapshot: persistable(task),
          statusTimestamp,
          expiresAt,
          updatedAt: new Date(),
        },
        setWhere: and(
          eq(tasks.companyId, owner.companyId),
          eq(tasks.userId, owner.userId),
          eq(tasks.contextId, task.contextId),
          terminalGuard(String(task.status?.state ?? 0)),
        ),
      })
      .returning({ id: tasks.id });
    if (!saved) {
      const existing = await this.database.query.tasks.findFirst({
        columns: { id: true },
        where: and(
          eq(tasks.id, task.id),
          eq(tasks.companyId, owner.companyId),
          eq(tasks.userId, owner.userId),
        ),
      });
      if (existing) {
        // A terminal task is immutable; late events are ignored.
        return;
      }
      throw new UnauthorizedException('task belongs to another tenant or user');
    }
  }

  /**
   * Inserts a new SUBMITTED task keyed by the client's messageId, so a retried send and a
   * concurrent send in the same context are both rejected by constraints, never by a race.
   */
  public async reserve(task: Task, context: ServerCallContext, clientMessageId: string) {
    const owner = identity(context);
    await this.authorization.context(owner, owner.publicationId, task.contextId);
    const statusTimestamp = new Date(task.status?.timestamp ?? Date.now());
    await this.database.insert(tasks).values({
      id: task.id,
      companyId: owner.companyId,
      userId: owner.userId,
      clientId: owner.clientId,
      contextId: task.contextId,
      state: String(task.status?.state ?? 0),
      userMessageId: task.id,
      clientMessageId,
      taskSnapshot: persistable(task),
      statusTimestamp,
      expiresAt: new Date(statusTimestamp.getTime() + this.config.taskRetentionDays * 86_400_000),
    });
  }

  /** Recovery write of the gateway's own snapshot; reads stay authorized per caller. */
  public async systemSave(companyId: string, task: Task): Promise<void> {
    await this.database
      .update(tasks)
      .set({
        state: String(task.status?.state ?? 0),
        taskSnapshot: persistable(task),
        statusTimestamp: new Date(task.status?.timestamp ?? Date.now()),
        heartbeatAt: new Date(),
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(tasks.id, task.id),
          eq(tasks.companyId, companyId),
          terminalGuard(String(task.status?.state ?? 0)),
        ),
      );
  }

  public async findSnapshot(companyId: string, taskId: string): Promise<Task | undefined> {
    const row = await this.database.query.tasks.findFirst({
      columns: { taskSnapshot: true },
      where: and(eq(tasks.id, taskId), eq(tasks.companyId, companyId)),
    });
    return row?.taskSnapshot as unknown as Task | undefined;
  }

  public async addBytes(companyId: string, taskId: string, bytesIn: number, bytesOut: number) {
    await this.database
      .update(tasks)
      .set({
        bytesIn: sql`${tasks.bytesIn} + ${bytesIn}`,
        bytesOut: sql`${tasks.bytesOut} + ${bytesOut}`,
      })
      .where(and(eq(tasks.id, taskId), eq(tasks.companyId, companyId)));
  }

  public async heartbeat(companyId: string, taskId: string): Promise<void> {
    await this.database
      .update(tasks)
      .set({ heartbeatAt: new Date() })
      .where(and(eq(tasks.id, taskId), eq(tasks.companyId, companyId)));
  }

  /** Non-terminal tasks whose executor stopped heartbeating, across tenants. */
  public async findOrphaned(before: Date, limit = 100) {
    return this.database
      .select({
        id: tasks.id,
        companyId: tasks.companyId,
        userId: tasks.userId,
        contextId: tasks.contextId,
        userMessageId: tasks.userMessageId,
        assistantMessageId: tasks.assistantMessageId,
        chatId: contexts.chatId,
        publicationId: contexts.publicationId,
        snapshot: tasks.taskSnapshot,
      })
      .from(tasks)
      .innerJoin(
        contexts,
        and(eq(contexts.companyId, tasks.companyId), eq(contexts.id, tasks.contextId)),
      )
      .where(
        and(
          notInArray(tasks.state, TERMINAL_STATES),
          or(
            lt(tasks.heartbeatAt, before),
            and(isNull(tasks.heartbeatAt), lt(tasks.updatedAt, before)),
          ),
        ),
      )
      .limit(limit);
  }

  public async findByClientMessage(
    context: ServerCallContext,
    contextId: string,
    clientMessageId: string,
  ): Promise<Task | undefined> {
    const owner = identity(context);
    const row = await this.database.query.tasks.findFirst({
      columns: { taskSnapshot: true },
      where: and(
        eq(tasks.companyId, owner.companyId),
        eq(tasks.userId, owner.userId),
        eq(tasks.contextId, contextId),
        eq(tasks.clientMessageId, clientMessageId),
      ),
    });
    return row?.taskSnapshot as unknown as Task | undefined;
  }

  public async load(taskId: string, context: ServerCallContext): Promise<Task | undefined> {
    const owner = identity(context);
    const row = await this.database.query.tasks.findFirst({
      columns: { taskSnapshot: true, contextId: true },
      where: and(
        eq(tasks.id, taskId),
        eq(tasks.companyId, owner.companyId),
        eq(tasks.userId, owner.userId),
      ),
    });
    if (!row) {
      return undefined;
    }
    try {
      await this.authorization.context(owner, owner.publicationId, row.contextId);
    } catch (error) {
      if (error instanceof NotFoundException) {
        return undefined;
      }
      throw error;
    }
    return row.taskSnapshot as unknown as Task;
  }

  public async list(
    params: ListTasksRequest,
    context: ServerCallContext,
  ): Promise<ListTasksResponse> {
    const owner = identity(context);
    await this.authorization.publication(owner, owner.publicationId);
    const pageSize = Math.min(100, Math.max(1, params.pageSize ?? 50));
    const filters: SQL[] = [
      eq(tasks.companyId, owner.companyId),
      eq(tasks.userId, owner.userId),
      inArray(
        tasks.contextId,
        this.database
          .select({ id: contexts.id })
          .from(contexts)
          .where(
            and(
              eq(contexts.companyId, owner.companyId),
              eq(contexts.userId, owner.userId),
              eq(contexts.publicationId, owner.publicationId),
            ),
          ),
      ),
    ];
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
