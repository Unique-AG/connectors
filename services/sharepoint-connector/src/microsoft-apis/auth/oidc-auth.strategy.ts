import assert from 'node:assert';
import { DefaultAzureCredential } from '@azure/identity';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { serializeError } from 'serialize-error-cjs';
import { z } from 'zod';
import { Config } from '../../config';
import { normalizeError } from '../../utils/normalize-error';
import { AuthStrategy } from './auth-strategy.interface';
import { TokenAcquisitionResult, TokenCache } from './token-cache';

const TokenResponseSchema = z.object({
  token: z.string().min(1),
  expiresOnTimestamp: z.number().positive(),
});

@Injectable()
export class OidcAuthStrategy implements AuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly credential: DefaultAzureCredential;
  private readonly tokenCache = new TokenCache();

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const sharePointConfig = this.configService.get('sharepoint', { infer: true });

    assert.strictEqual(
      sharePointConfig.authMode,
      'oidc',
      'OidcAuthStrategy called but authentication mode is not "oidc"',
    );

    this.credential = new DefaultAzureCredential({ tenantId: sharePointConfig.authTenantId });
  }

  public async getAccessToken(): Promise<string> {
    return this.tokenCache.getToken(() => this.acquireNewToken());
  }

  private async acquireNewToken(): Promise<TokenAcquisitionResult> {
    this.logger.log('Acquiring new Graph API token using OIDC');

    try {
      const tokenResponse = await this.credential.getToken('https://graph.microsoft.com/.default');
      const validatedResponse = TokenResponseSchema.parse(tokenResponse);

      return {
        token: validatedResponse.token,
        expiresAt: validatedResponse.expiresOnTimestamp,
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to acquire Graph API token using OIDC',
        error: serializeError(normalizeError(error)),
      });

      throw error;
    }
  }
}
