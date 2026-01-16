import { randomBytes } from 'node:crypto';
import { Inject, Injectable, Logger } from '@nestjs/common';
import * as bcrypt from 'bcrypt';
import { RegisterClientDto } from '../dtos/register-client.dto';
import type { IOAuthStore } from '../interfaces/io-auth-store.interface';
import { ClientRegistrationResponse, OAuthClient } from '../interfaces/oauth-client.interface';
import { OAUTH_STORE_TOKEN } from '../mcp-oauth.module-definition';

@Injectable()
export class ClientService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(OAUTH_STORE_TOKEN) private readonly store: IOAuthStore) {}

  /**
   * Register a client application per RFC 7591 Dynamic Client Registration.
   * Always creates a new client record. client_name is not treated as unique.
   * Returns the RFC 7591 compliant response with the plaintext secret (only time it's available).
   * @see https://datatracker.ietf.org/doc/html/rfc7591#section-3.2.1
   */
  public async registerClient(
    registerClientDto: RegisterClientDto,
  ): Promise<ClientRegistrationResponse> {
    this.logger.log({
      msg: 'Register new oAuth client',
      name: registerClientDto.client_name,
      description: registerClientDto.client_description,
      developerName: registerClientDto.developer_name,
      developerEmail: registerClientDto.developer_email,
      redirectUris: registerClientDto.redirect_uris,
      grantTypes: registerClientDto.grant_types,
      responseTypes: registerClientDto.response_types,
      tokenEndpointAuthMethod: registerClientDto.token_endpoint_auth_method,
    });

    const now = new Date();
    const clientId = this.store.generateClientId({
      ...registerClientDto,
      client_id: '',
      created_at: now,
      updated_at: now,
    });

    const plaintextSecret =
      registerClientDto.token_endpoint_auth_method !== 'none'
        ? randomBytes(32).toString('hex')
        : undefined;

    const hashedSecret = plaintextSecret ? await bcrypt.hash(plaintextSecret, 10) : undefined;

    const newClient: OAuthClient = {
      ...registerClientDto,
      client_id: clientId,
      client_secret: hashedSecret,
      created_at: now,
      updated_at: now,
    };

    this.logger.log({
      msg: 'Client registered with new id',
      name: newClient.client_name,
      clientId,
    });

    const storedClient = await this.store.storeClient(newClient);

    // Return RFC 7591 compliant response with plaintext secret (only time it's visible)
    const response: ClientRegistrationResponse = {
      client_id: storedClient.client_id,
      client_name: storedClient.client_name,
      client_description: storedClient.client_description,
      logo_uri: storedClient.logo_uri,
      client_uri: storedClient.client_uri,
      developer_name: storedClient.developer_name,
      developer_email: storedClient.developer_email,
      redirect_uris: storedClient.redirect_uris,
      grant_types: storedClient.grant_types,
      response_types: storedClient.response_types,
      token_endpoint_auth_method: storedClient.token_endpoint_auth_method,
      client_id_issued_at: Math.floor(storedClient.created_at.getTime() / 1000),
    };

    if (plaintextSecret) {
      response.client_secret = plaintextSecret;
      // RFC 7591: client_secret_expires_at is REQUIRED if client_secret is issued
      // 0 means the client_secret does not expire
      response.client_secret_expires_at = 0;
    }

    return response;
  }

  public async getClient(clientId: string): Promise<OAuthClient | null> {
    const client = await this.store.getClient(clientId);
    if (!client) return null;

    return client;
  }

  public async validateRedirectUri(clientId: string, redirectUri: string): Promise<boolean> {
    const client = await this.getClient(clientId);
    if (!client) return false;

    // Strict validation: no wildcards, exact match only
    // Exception: Allow localhost with different ports for development
    const isValid = client.redirect_uris.some((registeredUri) => {
      if (registeredUri === redirectUri) return true;

      // Allow loopback interface exceptions per RFC 8252
      try {
        const registered = new URL(registeredUri);
        const requested = new URL(redirectUri);

        // Only for localhost/127.0.0.1 - allow port variations
        if (
          (registered.hostname === 'localhost' || registered.hostname === '127.0.0.1') &&
          (requested.hostname === 'localhost' || requested.hostname === '127.0.0.1') &&
          registered.pathname === requested.pathname &&
          registered.search === requested.search
        ) {
          return true;
        }
      } catch {
        // Invalid URL, reject
      }

      return false;
    });

    if (!isValid) {
      this.logger.log({
        msg: 'Invalid redirect URI',
        clientId,
        requested: redirectUri,
        validRedirectUris: client.redirect_uris,
      });
    }

    return isValid;
  }

  /**
   * Validates client credentials using constant-time comparison.
   * @returns true if valid, false otherwise
   */
  public async validateClientCredentials(
    clientId: string,
    clientSecret: string | undefined,
  ): Promise<boolean> {
    const client = await this.getClient(clientId);
    if (!client) return false;

    // Public clients (token_endpoint_auth_method === 'none')
    if (!client.client_secret) return !clientSecret;

    // Confidential clients - require secret
    if (!clientSecret) return false;

    try {
      return await bcrypt.compare(clientSecret, client.client_secret);
    } catch (error) {
      this.logger.error({
        msg: 'Error comparing client secrets',
        error,
      });
      return false;
    }
  }
}
