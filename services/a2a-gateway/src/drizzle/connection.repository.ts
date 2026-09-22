import { ConflictException, Inject, Injectable } from '@nestjs/common';
import { and, eq, sql } from 'drizzle-orm';

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
  ): Promise<void> {
    const { id, ...configuration } = input;
    const [updated] = await this.database
      .update(connections)
      .set({
        ...configuration,
        version: sql`${connections.version} + 1`,
        updatedAt: new Date(),
        disabledAt: null,
        agentCardSnapshot: null,
        negotiatedCapabilities: {},
        lastVerifiedAt: null,
        lastError: null,
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
}
