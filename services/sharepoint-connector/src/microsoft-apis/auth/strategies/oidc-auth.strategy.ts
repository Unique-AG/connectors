import assert from 'node:assert';
import { DefaultAzureCredential } from '@azure/identity';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { z } from 'zod';
import { Config } from '../../../config';
import { sanitizeError } from '../../../utils/normalize-error';
import { TokenAcquisitionResult } from '../types';
import { AuthStrategy } from './auth-strategy.interface';

const TokenResponseSchema = z.object({
  token: z.string().min(1),
  expiresOnTimestamp: z.number().positive(),
});

@Injectable()
export class OidcAuthStrategy implements AuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly credential: DefaultAzureCredential;

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const sharePointConfig = this.configService.get('sharepoint', { infer: true });

    assert.strictEqual(
      sharePointConfig.auth.mode,
      'oidc',
      'OidcAuthStrategy called but authentication mode is not "oidc"',
    );

    this.credential = new DefaultAzureCredential({ tenantId: sharePointConfig.tenantId.value });
  }

  public async acquireNewToken(scopes: string[]): Promise<TokenAcquisitionResult> {
    this.logger.log('Acquiring new Graph API token using OIDC');

    try {
      const tokenResponse = await this.credential.getToken(scopes);
      const validatedResponse = TokenResponseSchema.parse(tokenResponse);

      return {
        token: validatedResponse.token,
        expiresAt: validatedResponse.expiresOnTimestamp,
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to acquire Graph API token using OIDC',
        error: sanitizeError(error),
      });

      throw error;
    }
  }
}
