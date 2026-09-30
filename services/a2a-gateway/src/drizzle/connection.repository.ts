import { ConflictException, Inject, Injectable } from '@nestjs/common';
import { and, eq, isNull, ne, sql } from 'drizzle-orm';

import { DRIZZLE, type GatewayDatabase } from './drizzle.module.js';
import { connections } from './schema/connections.table.js';

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

  public async replace(
    companyId: string,
    input: ConnectionWrite,
    expectedVersion: number,
    { keepVerification }: { keepVerification: boolean },
  ): Promise<void> {
    const { id, ...configuration } = input;
    const [updated] = await this.database
      .update(connections)
      .set({
        ...configuration,
        version: sql`${connections.version} + 1`,
        updatedAt: new Date(),
        disabledAt: null,
        ...(keepVerification
          ? {}
          : {
              agentCardSnapshot: null,
              negotiatedCapabilities: {},
              lastVerifiedAt: null,
              lastError: null,
            }),
      })
      .where(
        and(
          eq(connections.companyId, companyId),
          eq(connections.id, id),
          eq(connections.version, expectedVersion),
        ),
      )
      .returning({ id: connections.id });
    if (!updated) {
      throw new ConflictException('connection version does not match If-Match');
    }
  }

  public async revoke(
    companyId: string,
    connectionId: string,
    expectedVersion: number,
  ): Promise<void> {
    const [updated] = await this.database
      .update(connections)
      .set({
        credentialCiphertext: null,
        disabledAt: new Date(),
        updatedAt: new Date(),
        version: sql`${connections.version} + 1`,
      })
      .where(
        and(
          eq(connections.companyId, companyId),
          eq(connections.id, connectionId),
          eq(connections.version, expectedVersion),
        ),
      )
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

  public async recordVerification(
    companyId: string,
    connectionId: string,
    expectedVersion: number,
    result:
      | { agentCardSnapshot: Record<string, unknown>; negotiatedCapabilities: Record<string, unknown> }
      | { error: string },
  ): Promise<boolean> {
    const [updated] = await this.database
      .update(connections)
      .set(
        'error' in result
          ? { lastError: result.error, lastVerifiedAt: null, updatedAt: new Date() }
          : { ...result, lastError: null, lastVerifiedAt: new Date(), updatedAt: new Date() },
      )
      .where(
        and(
          eq(connections.companyId, companyId),
          eq(connections.id, connectionId),
          eq(connections.version, expectedVersion),
        ),
      )
      .returning({ id: connections.id });
    return updated !== undefined;
  }

  /**
   * Binds a connection to exactly one external space. Rebinding a space releases its previous
   * connection, which retention later purges together with other unbound connections.
   */
  public async bind(companyId: string, connectionId: string, assistantId: string): Promise<void> {
    await this.database.transaction(async (transaction) => {
      await transaction
        .update(connections)
        .set({ assistantId: null, updatedAt: new Date() })
        .where(
          and(
            eq(connections.companyId, companyId),
            eq(connections.assistantId, assistantId),
            ne(connections.id, connectionId),
          ),
        );
      const [bound] = await transaction
        .update(connections)
        .set({ assistantId, updatedAt: new Date() })
        .where(
          and(
            eq(connections.companyId, companyId),
            eq(connections.id, connectionId),
            sql`(${connections.assistantId} is null or ${connections.assistantId} = ${assistantId})`,
          ),
        )
        .returning({ id: connections.id });
      if (!bound) {
        throw new ConflictException('connection is bound to another space');
      }
    });
  }

  public async unbindAssistant(companyId: string, assistantId: string): Promise<void> {
    await this.database
      .update(connections)
      .set({ assistantId: null, updatedAt: new Date() })
      .where(and(eq(connections.companyId, companyId), eq(connections.assistantId, assistantId)));
  }

  public async deleteUnbound(companyId: string, connectionId: string): Promise<boolean> {
    const deleted = await this.database
      .delete(connections)
      .where(
        and(
          eq(connections.companyId, companyId),
          eq(connections.id, connectionId),
          isNull(connections.assistantId),
        ),
      )
      .returning({ id: connections.id });
    return deleted.length > 0;
  }
}
