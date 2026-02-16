import assert from 'node:assert';
import { Logger } from '@nestjs/common';
import { z } from 'zod';
import { AuthMode } from '../../config';
import { normalizeError, sanitizeError } from '../../utils/normalize-error';
import type { Redacted } from '../../utils/redacted';
import type { ConfluenceAuthStrategy, TokenResult } from './confluence-auth-strategy.interface';

interface OAuth2LoAuthConfig {
  mode: typeof AuthMode.OAUTH_2LO;
  clientId: string;
  clientSecret: Redacted<string>;
}

interface OAuth2LoConnectionConfig {
  instanceType: 'cloud' | 'data-center';
  baseUrl: string;
}

// Centralized Atlassian identity endpoint — same for all Cloud tenants
const CLOUD_TOKEN_ENDPOINT = 'https://api.atlassian.com/oauth/token';

// Data Center service accounts require an explicit scope in the token request
const DC_TOKEN_SCOPE = 'READ';

const tokenResponseSchema = z.object({
  access_token: z.string(),
  expires_in: z.number(),
});

export class OAuth2LoAuthStrategy implements ConfluenceAuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly clientId: string;
  private readonly clientSecret: string;
  private readonly tokenEndpoint: string;
  private readonly instanceType: 'cloud' | 'data-center';

  public constructor(authConfig: OAuth2LoAuthConfig, connectionConfig: OAuth2LoConnectionConfig) {
    this.clientId = authConfig.clientId;
    this.clientSecret = authConfig.clientSecret.value;
    this.instanceType = connectionConfig.instanceType;
    this.tokenEndpoint =
      connectionConfig.instanceType === 'cloud'
        ? CLOUD_TOKEN_ENDPOINT
        : `${connectionConfig.baseUrl}/rest/oauth2/latest/token`;
  }

  public async acquireToken(): Promise<TokenResult> {
    this.logger.log(`Acquiring Confluence ${this.instanceType} token via OAuth 2.0 2LO`);

    try {
      const response = await this.requestToken();
      return this.parseTokenResponse(response);
    } catch (error) {
      this.logger.error({
        msg: `Failed to acquire Confluence ${this.instanceType} token via OAuth 2.0 2LO`,
        error: sanitizeError(error),
      });

      throw error;
    }
  }

  private async requestToken(): Promise<Response> {
    const { headers, body } = this.buildRequest();

    let response: Response;
    try {
      response = await fetch(this.tokenEndpoint, {
        method: 'POST',
        headers,
        body,
      });
    } catch (error: unknown) {
      throw new Error(
        `Network error requesting token from ${this.tokenEndpoint}: ${normalizeError(error).message}`,
        { cause: error },
      );
    }

    if (!response.ok) {
      await this.handleErrorResponse(response);
    }

    return response;
  }

  private async handleErrorResponse(response: Response): Promise<never> {
    const body = await response.text().catch(() => 'Unable to read response body');
    const { status } = response;

    if (status === 401 || status === 403) {
      throw new Error(
        `Invalid credentials: ${this.tokenEndpoint} responded with ${status}: ${body}`,
      );
    }

    throw new Error(`Token request to ${this.tokenEndpoint} failed with status ${status}: ${body}`);
  }

  private buildRequest(): { headers: Record<string, string>; body: string } {
    const payload = {
      grant_type: 'client_credentials',
      client_id: this.clientId,
      client_secret: this.clientSecret,
    };

    if (this.instanceType === 'cloud') {
      return {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      };
    }

    return {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ ...payload, scope: DC_TOKEN_SCOPE }).toString(),
    };
  }

  private async parseTokenResponse(response: Response): Promise<TokenResult> {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new Error(`Malformed response from ${this.tokenEndpoint}: body is not valid JSON`);
    }

    const result = tokenResponseSchema.safeParse(body);
    assert.ok(
      result.success,
      `Malformed token response from ${this.tokenEndpoint}: ${result.error?.message}`,
    );

    const expiresAt = new Date(Date.now() + result.data.expires_in * 1000);
    return { accessToken: result.data.access_token, expiresAt };
  }
}
