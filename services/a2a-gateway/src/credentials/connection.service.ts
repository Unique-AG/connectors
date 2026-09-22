import { Injectable, Logger, NotFoundException } from '@nestjs/common';
import { typeid } from 'typeid-js';
import { AuthorizationService } from '../auth/authorization.service.js';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { ConnectionRepository } from '../drizzle/gateway.repository.js';
import type { ConnectionConfiguration } from './credential-profile.js';
import { CredentialVault } from './credential-vault.js';
import { EgressService } from './egress.service.js';

@Injectable()
export class ConnectionService {
  private readonly logger = new Logger(ConnectionService.name);

  public constructor(
    private readonly connections: ConnectionRepository,
    private readonly authorization: AuthorizationService,
    private readonly vault: CredentialVault,
    private readonly egress: EgressService,
  ) {}

  public async list(identity: RequestIdentity) {
    await this.authorization.manageConnections(identity);
    const connections = await this.connections.list(identity.companyId);
    return connections.map((connection) => this.summary(connection));
  }

  public async get(identity: RequestIdentity, connectionId: string) {
    await this.authorization.manageConnections(identity);
    return this.summary(await this.find(identity.companyId, connectionId));
  }

  public async save(
    identity: RequestIdentity,
    configuration: ConnectionConfiguration,
    existing?: { id: string; version: number },
  ) {
    await this.authorization.manageConnections(identity);
    await this.authorization.assertNewUse(identity);
    if (existing) {
      await this.find(identity.companyId, existing.id);
    }
    this.egress.approve(configuration.agentCardUrl);
    if (configuration.credential.type === 'oauth2_client_credentials') {
      this.egress.approve(configuration.credential.tokenEndpoint);
    }
    const id = existing?.id ?? typeid('conn').toString();
    const credentialCiphertext = this.vault.seal(
      JSON.stringify({
        companyId: identity.companyId,
        connectionId: id,
        origin: new URL(configuration.agentCardUrl).origin,
        profile: configuration.credential,
      }),
    );
    const input = {
      id,
      name: configuration.name,
      agentCardUrl: configuration.agentCardUrl,
      credentialType: configuration.credential.type,
      credentialCiphertext,
    };
    if (existing) {
      await this.connections.replace(identity.companyId, input, existing.version);
    } else {
      await this.connections.create(identity.companyId, input);
    }
    this.logger.log({
      action: 'connection.configure',
      companyId: identity.companyId,
      userId: identity.userId,
      connectionId: id,
    });
    return this.summary(await this.find(identity.companyId, id));
  }

  public async revoke(
    identity: RequestIdentity,
    connectionId: string,
    expectedVersion: number,
  ): Promise<void> {
    await this.authorization.manageConnections(identity);
    await this.find(identity.companyId, connectionId);
    await this.connections.revoke(identity.companyId, connectionId, expectedVersion);
    this.logger.log({
      action: 'connection.revoke',
      companyId: identity.companyId,
      userId: identity.userId,
      connectionId,
    });
  }

  private async find(companyId: string, connectionId: string) {
    const connection = await this.connections.find(companyId, connectionId);
    if (!connection) {
      throw new NotFoundException('connection not found');
    }
    return connection;
  }

  private summary(connection: NonNullable<Awaited<ReturnType<ConnectionRepository['find']>>>) {
    return {
      id: connection.id,
      name: connection.name,
      agentCardUrl: connection.agentCardUrl,
      credentialType: connection.credentialType,
      version: connection.version,
      disabled: connection.disabledAt !== null,
      remotePermissions: 'shared' as const,
    };
  }
}
