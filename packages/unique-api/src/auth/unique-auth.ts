import assert from 'node:assert';
import { Logger } from '@nestjs/common';
import type { Dispatcher } from 'undici';
import { UniqueAuthConfig } from '../core/config/unique-api-auth-schema';
import type { UniqueApiMetrics } from '../core/observability';
import type { ExternalAuthConfig, UniqueApiAuth } from '../types';

export class UniqueAuth implements UniqueApiAuth {
  // used protected to allow use of typeguard isTokenValid
  protected cachedToken?: string;
  private tokenExpirationTime?: number;
  private refreshTokenPromise: Promise<string> | null = null;

  public constructor(
    private readonly config: UniqueAuthConfig,
    private readonly metrics: UniqueApiMetrics,
    private readonly logger: Logger,
    private readonly dispatcher: Dispatcher,
  ) {}

  public async getToken(): Promise<string> {
    if (this.isTokenValid()) {
      return this.cachedToken;
    }

    assert.strictEqual(
      this.config.mode,
      'external',
      'getToken() called but auth mode is not "external"',
    );

    if (this.refreshTokenPromise) {
      return this.refreshTokenPromise;
    }

    this.refreshTokenPromise = this.refreshToken(this.config).finally(() => {
      this.refreshTokenPromise = null;
    });
    return this.refreshTokenPromise;
  }

  public async getAuthHeaders(): Promise<Record<string, string>> {
    if (this.config.mode === 'cluster_local') {
      return {
        'x-service-id': this.config.serviceId,
        ...this.config.extraHeaders,
      };
    }
    const token = await this.getToken();
    return { Authorization: `Bearer ${token}` };
  }

  private async refreshToken(config: ExternalAuthConfig): Promise<string> {
    const { zitadelOauthTokenUrl, zitadelClientId, zitadelClientSecret, zitadelProjectId } = config;

    const params = new URLSearchParams({
      scope:
        `openid profile email urn:zitadel:iam:user:resourceowner ` +
        `urn:zitadel:iam:org:projects:roles urn:zitadel:iam:org:project:id:${zitadelProjectId}:aud`,
      grant_type: 'client_credentials',
    });

    try {
      const basicAuth = Buffer.from(`${zitadelClientId}:${zitadelClientSecret}`).toString('base64');
      const { statusCode, body } = await this.dispatcher.request({
        origin: new URL(zitadelOauthTokenUrl).origin,
        path: new URL(zitadelOauthTokenUrl).pathname,
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          Authorization: `Basic ${basicAuth}`,
        },
        body: params.toString(),
      });

      if (statusCode < 200 || statusCode >= 300) {
        const errorText = await body.text().catch(() => 'No response body');
        throw new Error(
          `Zitadel token request failed with status ${statusCode}. ` +
            `URL: ${zitadelOauthTokenUrl}, Response: ${errorText}`,
        );
      }

      const tokenData = (await body.json()) as ZitadelTokenResponse;
      assert.ok(tokenData.access_token, 'Invalid token response: missing access_token');

      const expiresIn = tokenData.expires_in;
      if (typeof expiresIn !== 'number' || !Number.isFinite(expiresIn) || expiresIn <= 0) {
        throw new Error(
          `Invalid token response: expires_in must be a positive number, got ${String(expiresIn)}`,
        );
      }

      this.cachedToken = tokenData.access_token;
      this.tokenExpirationTime = Date.now() + expiresIn * 1000;

      this.metrics.authTokenRefreshTotal.add(1);

      return tokenData.access_token;
    } catch (error) {
      this.logger.error('Failed to acquire Unique API token from Zitadel', error);
      throw error;
    }
  }

  private isTokenValid(): this is this & { cachedToken: string } {
    return Boolean(
      this.cachedToken && this.tokenExpirationTime && Date.now() < this.tokenExpirationTime,
    );
  }
}

interface ZitadelTokenResponse {
  access_token: string;
  expires_in: number;
  token_type?: string;
  id_token?: string;
}
