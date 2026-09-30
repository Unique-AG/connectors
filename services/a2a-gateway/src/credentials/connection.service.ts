import type { AgentCard } from '@a2a-js/sdk';
import { ClientFactory, JsonRpcTransportFactory } from '@a2a-js/sdk/client';
import {
  BadRequestException,
  ConflictException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { typeid } from 'typeid-js';
import { AuthorizationService } from '../auth/authorization.service.js';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { ConnectionRepository } from '../drizzle/connection.repository.js';
import { isForeignKeyViolation } from '../drizzle/unique-violation.js';
import { AuditLog } from '../observability/audit-log.service.js';
import {
  cardPreview,
  IncompatibleAgentError,
  type NegotiatedCapabilities,
  negotiate,
  parseAgentCard,
} from './agent-card.js';
import type { ConnectionConfiguration, CredentialProfile } from './credential-profile.js';
import { CredentialProviderService } from './credential-provider.service.js';
import { CredentialVault } from './credential-vault.js';
import { EgressBlockedError, EgressService } from './egress.service.js';

const MAX_CARD_BYTES = 256 * 1024;

type StoredConnection = NonNullable<Awaited<ReturnType<ConnectionRepository['find']>>>;

function rootCause(error: unknown): unknown {
  return error instanceof Error && error.cause ? rootCause(error.cause) : error;
}

function verificationError(error: unknown): string {
  if (error instanceof IncompatibleAgentError) {
    return error.message;
  }
  if (error instanceof BadRequestException) {
    return 'The agent host is not allowed by the gateway egress policy (HTTPS and an operator-approved host are required).';
  }
  if (rootCause(error) instanceof EgressBlockedError) {
    return 'The agent host resolves to a private or reserved network address.';
  }
  return 'The agent could not be reached. Check the URL, its TLS certificate and network access.';
}

@Injectable()
export class ConnectionService {
  public constructor(
    private readonly connections: ConnectionRepository,
    private readonly authorization: AuthorizationService,
    private readonly vault: CredentialVault,
    private readonly egress: EgressService,
    private readonly credentials: CredentialProviderService,
    private readonly audit: AuditLog,
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

  /** Redacted state for core, which validates the connection of an external space it saves. */
  public async internalSummary(identity: RequestIdentity, connectionId: string) {
    return this.summary(await this.find(identity.companyId, connectionId));
  }

  public async save(
    identity: RequestIdentity,
    configuration: ConnectionConfiguration,
    existing?: { id: string; version: number },
  ) {
    await this.authorization.manageConnections(identity);
    await this.authorization.assertNewUse(identity);
    const previous = existing ? await this.find(identity.companyId, existing.id) : undefined;
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
      await this.connections.replace(identity.companyId, input, existing.version, {
        keepVerification: previous?.agentCardUrl === configuration.agentCardUrl,
      });
    } else {
      await this.connections.create(identity.companyId, input);
    }
    this.audit.record(existing ? 'connection.rotate' : 'connection.create', identity, {
      connectionId: id,
      credentialType: configuration.credential.type,
    });
    return this.summary(await this.find(identity.companyId, id));
  }

  /**
   * Fetches and validates the remote Agent Card through the egress guard, stores the negotiated
   * capabilities and returns a preview. Only a verified connection can run executions.
   */
  public async test(identity: RequestIdentity, connectionId: string) {
    await this.authorization.manageConnections(identity);
    await this.authorization.assertNewUse(identity);
    const connection = await this.connections.findWithCredential(identity.companyId, connectionId);
    if (!connection) {
      throw new NotFoundException('connection not found');
    }
    if (connection.disabledAt || !connection.credentialCiphertext) {
      throw new ConflictException('connection is disabled');
    }
    let result:
      | { ok: true; card: AgentCard; capabilities: NegotiatedCapabilities }
      | { ok: false; error: string };
    try {
      const cardUrl = this.egress.approve(connection.agentCardUrl);
      const headers = await this.credentials.connectionHeaders(
        identity.companyId,
        connection,
        cardUrl,
      );
      const response = await this.egress.fetch(
        cardUrl,
        { headers: { ...headers, accept: 'application/json' } },
        MAX_CARD_BYTES,
      );
      if (!response.ok) {
        throw new IncompatibleAgentError(
          `The agent card request returned HTTP ${response.status}.`,
        );
      }
      const credentialType = (connection.credentialType ?? 'none') as CredentialProfile['type'];
      let card = parseAgentCard(await response.json().catch(() => undefined));
      let capabilities = negotiate(card, cardUrl, credentialType);
      if (capabilities.extendedAgentCard) {
        card = parseAgentCard(await this.extendedCard(identity.companyId, connection, card));
        capabilities = negotiate(card, cardUrl, credentialType);
      }
      result = { ok: true, card, capabilities };
    } catch (error) {
      result = { ok: false, error: verificationError(error) };
    }
    const recorded = await this.connections.recordVerification(
      identity.companyId,
      connectionId,
      connection.version,
      result.ok
        ? {
            agentCardSnapshot: JSON.parse(JSON.stringify(result.card)) as Record<string, unknown>,
            negotiatedCapabilities: { ...result.capabilities },
          }
        : { error: result.error },
    );
    if (!recorded) {
      throw new ConflictException('connection changed during the test; retry');
    }
    this.audit.record('connection.test', identity, {
      connectionId,
      ok: result.ok,
    });
    return result.ok
      ? { ok: true, agent: cardPreview(result.card), capabilities: result.capabilities }
      : { ok: false, error: result.error };
  }

  /** Removes a connection no space uses, e.g. after a space could not be created. */
  public async remove(identity: RequestIdentity, connectionId: string): Promise<void> {
    await this.authorization.manageConnections(identity);
    await this.find(identity.companyId, connectionId);
    let deleted: boolean;
    try {
      deleted = await this.connections.deleteUnbound(identity.companyId, connectionId);
    } catch (error) {
      if (isForeignKeyViolation(error)) {
        throw new ConflictException('connection has execution history; revoke it instead');
      }
      throw error;
    }
    if (!deleted) {
      throw new ConflictException('connection is used by a space');
    }
    this.audit.record('connection.delete', identity, {
      connectionId,
    });
  }

  /** Called by core after it saved an external space under the effective (managing) user. */
  public async bind(identity: RequestIdentity, connectionId: string, assistantId: string) {
    await this.authorization.manageSpace(identity, assistantId);
    const connection = await this.find(identity.companyId, connectionId);
    if (connection.disabledAt || !connection.lastVerifiedAt || connection.lastError) {
      throw new ConflictException('connection is disabled or not verified');
    }
    await this.connections.bind(identity.companyId, connectionId, assistantId);
    this.audit.record('connection.bind', identity, {
      connectionId,
      assistantId,
    });
    return this.summary(await this.find(identity.companyId, connectionId));
  }

  public async revoke(
    identity: RequestIdentity,
    connectionId: string,
    expectedVersion: number,
  ): Promise<void> {
    await this.authorization.manageConnections(identity);
    await this.find(identity.companyId, connectionId);
    await this.connections.revoke(identity.companyId, connectionId, expectedVersion);
    this.audit.record('connection.revoke', identity, {
      connectionId,
    });
  }

  private async extendedCard(
    companyId: string,
    connection: NonNullable<Awaited<ReturnType<ConnectionRepository['findWithCredential']>>>,
    card: AgentCard,
  ): Promise<AgentCard> {
    const fetchImpl = async (input: string | URL | Request, init: RequestInit = {}) => {
      const url = this.egress.approve(input instanceof Request ? input.url : input.toString());
      const headers = new Headers(init.headers);
      for (const [name, value] of Object.entries(
        await this.credentials.connectionHeaders(companyId, connection, url),
      )) {
        headers.set(name, value);
      }
      return this.egress.fetch(url, { ...init, headers }, MAX_CARD_BYTES);
    };
    const client = await new ClientFactory({
      transports: [new JsonRpcTransportFactory({ fetchImpl: fetchImpl as typeof fetch })],
      preferredTransports: ['JSONRPC'],
    }).createFromAgentCard(card);
    return client.getAgentCard();
  }

  private async find(companyId: string, connectionId: string) {
    const connection = await this.connections.find(companyId, connectionId);
    if (!connection) {
      throw new NotFoundException('connection not found');
    }
    return connection;
  }

  private summary(connection: StoredConnection) {
    const card = connection.agentCardSnapshot as AgentCard | null;
    return {
      id: connection.id,
      name: connection.name,
      agentCardUrl: connection.agentCardUrl,
      credentialType: connection.credentialType,
      version: connection.version,
      disabled: connection.disabledAt !== null,
      bound: Boolean(connection.assistantId),
      assistantId: connection.assistantId ?? null,
      verified: Boolean(connection.lastVerifiedAt) && !connection.lastError,
      verifiedAt: connection.lastVerifiedAt?.toISOString() ?? null,
      lastError: connection.lastError ?? null,
      agent: card ? cardPreview(card) : null,
      capabilities: connection.negotiatedCapabilities ?? {},
      remotePermissions: 'shared' as const,
    };
  }
}
