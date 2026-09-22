import { ConflictException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import { and, eq, sql } from 'drizzle-orm';

import { DRIZZLE, type GatewayDatabase } from './drizzle.module.js';
import { connections } from './schema/connections.table.js';
import { executions } from './schema/executions.table.js';
import { publications } from './schema/publications.table.js';
import { remoteContexts } from './schema/remote-contexts.table.js';

export interface TenantPrincipal {
  companyId: string;
  userId: string;
}

export interface PublicationWrite {
  assistantId: string;
  enabled: boolean;
  cardOverrides?: Record<string, unknown>;
  skills?: unknown[];
}

@Injectable()
export class PublicationRepository {
  public constructor(@Inject(DRIZZLE) private readonly database: GatewayDatabase) {}

  public async findByAssistant(companyId: string, assistantId: string) {
    return this.database.query.publications.findFirst({
      where: and(eq(publications.companyId, companyId), eq(publications.assistantId, assistantId)),
    });
  }

  public async upsert(principal: TenantPrincipal, input: PublicationWrite, expectedVersion?: number) {
    const existing = await this.findByAssistant(principal.companyId, input.assistantId);
    if (existing && expectedVersion !== existing.version) {
      throw new ConflictException('publication version does not match If-Match');
    }

    if (!existing) {
      const [created] = await this.database
        .insert(publications)
        .values({
          companyId: principal.companyId,
          createdByUserId: principal.userId,
          ...input,
        })
        .returning();
      return created;
    }

    const [updated] = await this.database
      .update(publications)
      .set({
        enabled: input.enabled,
        cardOverrides: input.cardOverrides ?? {},
        skills: input.skills ?? [],
        disabledAt: input.enabled ? null : new Date(),
        version: sql`${publications.version} + 1`,
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(publications.id, existing.id),
          eq(publications.companyId, principal.companyId),
          eq(publications.version, existing.version),
        ),
      )
      .returning();
    if (!updated) throw new ConflictException('publication was modified concurrently');
    return updated;
  }

  public async disable(companyId: string, assistantId: string): Promise<void> {
    await this.database
      .update(publications)
      .set({ enabled: false, disabledAt: new Date(), updatedAt: new Date() })
      .where(and(eq(publications.companyId, companyId), eq(publications.assistantId, assistantId)));
  }
}

export interface ConnectionWrite {
  id: string;
  name: string;
  agentCardUrl: string;
  credentialType: string;
  credentialCiphertext: Buffer;
}

@Injectable()
export class ConnectionRepository {
  public constructor(@Inject(DRIZZLE) private readonly database: GatewayDatabase) {}

  public async find(companyId: string, connectionId: string) {
    return this.database.query.connections.findFirst({
      columns: { credentialCiphertext: false },
      where: and(eq(connections.companyId, companyId), eq(connections.id, connectionId)),
    });
  }

  public async findWithCredential(companyId: string, connectionId: string) {
    return this.database.query.connections.findFirst({
      where: and(eq(connections.companyId, companyId), eq(connections.id, connectionId)),
    });
  }

  public async list(companyId: string) {
    return this.database.query.connections.findMany({
      columns: { credentialCiphertext: false },
      where: eq(connections.companyId, companyId),
    });
  }

  public async replace(companyId: string, input: ConnectionWrite, expectedVersion: number): Promise<void> {
    const { id, ...configuration } = input;
    const [updated] = await this.database.update(connections).set({
      ...configuration, version: sql`${connections.version} + 1`, updatedAt: new Date(),
      disabledAt: null, agentCardSnapshot: null, negotiatedCapabilities: {}, lastVerifiedAt: null, lastError: null,
    }).where(and(eq(connections.companyId, companyId), eq(connections.id, id), eq(connections.version, expectedVersion)))
      .returning({ id: connections.id });
    if (!updated) {
      throw new ConflictException('connection version does not match If-Match');
    }
  }

  public async revoke(companyId: string, connectionId: string, expectedVersion: number): Promise<void> {
    const [updated] = await this.database.update(connections).set({
      credentialCiphertext: null, disabledAt: new Date(), updatedAt: new Date(),
      version: sql`${connections.version} + 1`,
    }).where(and(eq(connections.companyId, companyId), eq(connections.id, connectionId), eq(connections.version, expectedVersion)))
      .returning({ id: connections.id });
    if (!updated) {
      throw new ConflictException('connection version does not match If-Match');
    }
  }

  public async create(companyId: string, input: ConnectionWrite) {
    const [connection] = await this.database
      .insert(connections)
      .values({ companyId, ...input })
      .returning({
        id: connections.id,
        companyId: connections.companyId,
        name: connections.name,
        agentCardUrl: connections.agentCardUrl,
        version: connections.version,
      });
    return connection;
  }
}

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
    if (created) return created;

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
    if (!execution) throw new NotFoundException('execution not found');
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
    if (created) return created;
    const existing = await this.database.query.remoteContexts.findFirst({
      where: and(eq(remoteContexts.companyId, companyId), eq(remoteContexts.chatId, chatId)),
    });
    if (!existing) throw new NotFoundException('remote context not found');
    return existing;
  }
}
