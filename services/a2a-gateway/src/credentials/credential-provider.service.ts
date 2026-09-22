import {
  BadRequestException,
  ForbiddenException,
  Injectable,
  ServiceUnavailableException,
} from '@nestjs/common';
import * as oauth from 'oauth4webapi';
import { z } from 'zod';
import { AuthorizationService } from '../auth/authorization.service.js';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { ConnectionRepository, ExecutionRepository } from '../drizzle/gateway.repository.js';
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
  ) {}

  public async request(
    identity: RequestIdentity,
    assistantId: string,
    connectionId: string,
    destination: string,
    body?: string,
    executionId?: string,
  ): Promise<Response> {
    if (executionId) {
      const execution = await this.executions.findOwned(identity, executionId);
      if (
        execution.assistantId !== assistantId ||
        execution.connectionId !== connectionId ||
        !['submitted', 'working', 'input-required', 'auth-required'].includes(execution.state)
      ) {
        throw new ForbiddenException('active execution access required');
      }
    } else {
      await this.authorization.assertNewUse(identity);
    }
    const assistant = externalAssistant.safeParse(
      await this.unique.getAssistant(identity, assistantId),
    );
    if (
      !assistant.success ||
      assistant.data.id !== assistantId ||
      assistant.data.a2aConnectionId !== connectionId
    ) {
      throw new ForbiddenException('connection is not authorized for this space');
    }
    const connection = await this.connections.findWithCredential(identity.companyId, connectionId);
    if (!connection || connection.disabledAt || !connection.credentialCiphertext) {
      throw new ForbiddenException('connection is unavailable');
    }
    const url = this.egress.approve(destination);
    if (url.origin !== new URL(connection.agentCardUrl).origin) {
      throw new BadRequestException('credential destination does not match the connection');
    }
    let profile: CredentialProfile;
    try {
      const envelope = envelopeSchema.parse(
        JSON.parse(this.vault.open(connection.credentialCiphertext)),
      );
      if (
        envelope.companyId !== identity.companyId ||
        envelope.connectionId !== connectionId ||
        envelope.origin !== url.origin ||
        envelope.profile.type !== connection.credentialType
      ) {
        throw new Error('credential scope mismatch');
      }
      profile = envelope.profile;
    } catch {
      throw new ForbiddenException('connection credential is unavailable');
    }
    const headers = new Headers({ 'content-type': 'application/json' });
    if (profile.type === 'bearer') {
      headers.set('authorization', `Bearer ${profile.token}`);
    } else if (profile.type === 'api_key') {
      headers.set(profile.header, profile.value);
    } else if (profile.type === 'oauth2_client_credentials') {
      headers.set(
        'authorization',
        `Bearer ${await this.token(identity.companyId, connectionId, connection.version, profile)}`,
      );
    }
    // A rotation/revocation during a token refresh must not release the stale credential.
    const current = await this.connections.find(identity.companyId, connectionId);
    if (!current || current.disabledAt || current.version !== connection.version) {
      throw new ForbiddenException('connection changed; retry the request');
    }
    const response = await this.egress.fetch(url, {
      method: body === undefined ? 'GET' : 'POST',
      body,
      headers,
    });
    if (response.status === 401) {
      this.tokens.delete(`${identity.companyId}:${connectionId}`);
    }
    return response;
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
