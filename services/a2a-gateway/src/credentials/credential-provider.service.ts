import {
  BadRequestException,
  ForbiddenException,
  Inject,
  Injectable,
  ServiceUnavailableException,
} from '@nestjs/common';
import * as oauth from 'oauth4webapi';
import { z } from 'zod';
import { AuthorizationService } from '../auth/authorization.service.js';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { ConnectionRepository } from '../drizzle/connection.repository.js';
import { ACTIVE_EXECUTION_STATES, ExecutionRepository } from '../drizzle/execution.repository.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { type CredentialProfile, credentialProfile } from './credential-profile.js';
import { CredentialVault } from './credential-vault.js';
import { EgressService } from './egress.service.js';

const envelopeSchema = z.object({
  companyId: z.string(),
  connectionId: z.string(),
  origin: z.string(),
  profile: credentialProfile,
});

const externalAssistant = z.object({
  id: z.string(),
  executionProvider: z.literal('A2A'),
  a2aConnectionId: z.string(),
});

interface CachedToken {
  token: string;
  expiresAt: number;
}

interface CredentialedConnection {
  id: string;
  companyId: string;
  version: number;
  agentCardUrl: string;
  credentialType: string | null;
  credentialCiphertext: Buffer | null;
  disabledAt: Date | null;
}

export interface RemoteScope {
  assistantId: string;
  connectionId: string;
  executionId?: string;
}

export type RemoteFetch = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

/**
 * Releases a connection's shared credential only to that connection's origin, only for a caller
 * who may currently use the external space, and never together with any Unique identity.
 */
@Injectable()
export class CredentialProviderService {
  private readonly tokens = new Map<string, { version: number; result: Promise<CachedToken> }>();

  public constructor(
    private readonly connections: ConnectionRepository,
    private readonly authorization: AuthorizationService,
    private readonly unique: UniqueInternalClient,
    private readonly vault: CredentialVault,
    private readonly egress: EgressService,
    private readonly executions: ExecutionRepository,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  /**
   * Authorizes the caller once and returns a fetch bound to the connection. Every request still
   * re-checks that the execution is active and that the connection was not rotated or revoked.
   */
  public async remoteFetch(identity: RequestIdentity, scope: RemoteScope): Promise<RemoteFetch> {
    await this.authorizeScope(identity, scope);
    const connection = await this.connections.findWithCredential(
      identity.companyId,
      scope.connectionId,
    );
    if (
      !connection ||
      connection.disabledAt ||
      !connection.credentialCiphertext ||
      connection.assistantId !== scope.assistantId
    ) {
      throw new ForbiddenException('connection is unavailable');
    }
    const origin = new URL(connection.agentCardUrl).origin;
    const profile = this.openProfile(identity.companyId, connection, origin);
    return async (input, init = {}) => {
      const destination = input instanceof Request ? input.url : input.toString();
      const url = this.egress.approve(destination);
      if (url.origin !== origin) {
        throw new BadRequestException('credential destination does not match the connection');
      }
      if (scope.executionId) {
        await this.assertActiveExecution(identity, scope);
      }
      const headers = new Headers(init.headers);
      for (const [name, value] of Object.entries(
        await this.credentialHeaders(identity.companyId, connection, profile),
      )) {
        headers.set(name, value);
      }
      await this.assertUnchanged(identity.companyId, connection);
      const response = await this.egress.stream(
        url,
        { ...init, headers },
        this.config.maxRemoteFileBytes * 2,
      );
      if (response.status === 401) {
        this.tokens.delete(`${identity.companyId}:${connection.id}`);
      }
      return response;
    };
  }

  /** Headers for a management-time request (connection test) to the connection's own origin. */
  public async connectionHeaders(
    companyId: string,
    connection: CredentialedConnection,
    destination: URL,
  ): Promise<Record<string, string>> {
    const origin = new URL(connection.agentCardUrl).origin;
    if (destination.origin !== origin || !connection.credentialCiphertext) {
      return {};
    }
    return this.credentialHeaders(
      companyId,
      connection,
      this.openProfile(companyId, connection, origin),
    );
  }

  private async authorizeScope(identity: RequestIdentity, scope: RemoteScope): Promise<void> {
    if (scope.executionId) {
      await this.assertActiveExecution(identity, scope);
    } else {
      await this.authorization.assertNewUse(identity);
    }
    const assistant = externalAssistant.safeParse(
      await this.unique.getAssistant(identity, scope.assistantId),
    );
    if (
      !assistant.success ||
      assistant.data.id !== scope.assistantId ||
      assistant.data.a2aConnectionId !== scope.connectionId
    ) {
      throw new ForbiddenException('connection is not authorized for this space');
    }
  }

  private async assertActiveExecution(identity: RequestIdentity, scope: RemoteScope) {
    const execution = await this.executions.findOwned(identity, scope.executionId ?? '');
    if (
      execution.assistantId !== scope.assistantId ||
      execution.connectionId !== scope.connectionId ||
      !ACTIVE_EXECUTION_STATES.includes(execution.state)
    ) {
      throw new ForbiddenException('active execution access required');
    }
  }

  // A rotation/revocation during a token refresh must not release the stale credential.
  private async assertUnchanged(companyId: string, connection: CredentialedConnection) {
    const current = await this.connections.find(companyId, connection.id);
    if (!current || current.disabledAt || current.version !== connection.version) {
      throw new ForbiddenException('connection changed; retry the request');
    }
  }

  private openProfile(
    companyId: string,
    connection: CredentialedConnection,
    origin: string,
  ): CredentialProfile {
    try {
      const envelope = envelopeSchema.parse(
        JSON.parse(this.vault.open(connection.credentialCiphertext ?? Buffer.alloc(0))),
      );
      if (
        envelope.companyId !== companyId ||
        envelope.connectionId !== connection.id ||
        envelope.origin !== origin ||
        envelope.profile.type !== connection.credentialType
      ) {
        throw new Error('credential scope mismatch');
      }
      return envelope.profile;
    } catch {
      throw new ForbiddenException('connection credential is unavailable');
    }
  }

  private async credentialHeaders(
    companyId: string,
    connection: CredentialedConnection,
    profile: CredentialProfile,
  ): Promise<Record<string, string>> {
    if (profile.type === 'bearer') {
      return { authorization: `Bearer ${profile.token}` };
    }
    if (profile.type === 'api_key') {
      return { [profile.header]: profile.value };
    }
    if (profile.type === 'oauth2_client_credentials') {
      return {
        authorization: `Bearer ${await this.token(companyId, connection.id, connection.version, profile)}`,
      };
    }
    return {};
  }

  private async token(
    companyId: string,
    connectionId: string,
    version: number,
    profile: Extract<CredentialProfile, { type: 'oauth2_client_credentials' }>,
  ): Promise<string> {
    const key = `${companyId}:${connectionId}`;
    const cached = this.tokens.get(key);
    if (cached?.version === version) {
      try {
        const result = await cached.result;
        if (result.expiresAt > Date.now()) {
          return result.token;
        }
        if (this.tokens.get(key) !== cached) {
          return this.token(companyId, connectionId, version, profile);
        }
        this.tokens.delete(key);
      } catch {
        throw new ServiceUnavailableException('remote authentication failed');
      }
    }
    const result = this.obtainToken(profile);
    const entry = { version, result };
    this.tokens.delete(key);
    if (this.tokens.size >= 1000) {
      const oldest = this.tokens.keys().next().value;
      if (oldest) {
        this.tokens.delete(oldest);
      }
    }
    this.tokens.set(key, entry);
    try {
      return (await result).token;
    } catch {
      if (this.tokens.get(key) === entry) {
        this.tokens.delete(key);
      }
      throw new ServiceUnavailableException('remote authentication failed');
    }
  }

  private async obtainToken(
    profile: Extract<CredentialProfile, { type: 'oauth2_client_credentials' }>,
  ): Promise<CachedToken> {
    const server = {
      issuer: profile.issuer,
      token_endpoint: this.egress.approve(profile.tokenEndpoint).toString(),
    };
    const client = { client_id: profile.clientId };
    const authentication =
      profile.authMethod === 'client_secret_basic'
        ? oauth.ClientSecretBasic(profile.clientSecret)
        : oauth.ClientSecretPost(profile.clientSecret);
    const parameters = new URLSearchParams(profile.scope ? { scope: profile.scope } : {});
    const response = await oauth.clientCredentialsGrantRequest(
      server,
      client,
      authentication,
      parameters,
      {
        [oauth.customFetch]: (url, init) => this.egress.fetch(url, init),
        [oauth.allowInsecureRequests]: this.config.egressAllowInsecure,
      },
    );
    const token = await oauth.processClientCredentialsResponse(server, client, response);
    if (
      token.token_type.toLowerCase() !== 'bearer' ||
      !/^[A-Za-z0-9\-._~+/]+=*$/.test(token.access_token)
    ) {
      throw new Error('unsupported remote token');
    }
    return {
      token: token.access_token,
      expiresAt: Date.now() + Math.max(0, (token.expires_in ?? 0) - 30) * 1000,
    };
  }
}
