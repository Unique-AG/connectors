import { DefaultAzureCredential } from '@azure/identity';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { serializeError } from 'serialize-error-cjs';
import { z } from 'zod';
import { Config } from '../../config';
import { normalizeError } from '../../utils/normalize-error';
import { GraphAuthStrategy } from './graph-auth-strategy.interface';
import { TokenAcquisitionResult, TokenCache } from './token-cache';

const TokenResponseSchema = z.object({
  token: z.string().min(1),
  expiresOnTimestamp: z.number().positive(),
});

/**
 * OIDC/Workload Identity authentication strategy for Microsoft Graph API.
 * Used in AKS environments with Azure Workload Identity enabled.
 */
@Injectable()
export class OidcGraphAuthStrategy implements GraphAuthStrategy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly credential: DefaultAzureCredential;
  private readonly tokenCache = new TokenCache();

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const tenantId = this.configService.get('sharepoint.graphTenantId', { infer: true });
    // const clientId = this.configService.get('sharepoint.graphClientId', { infer: true });

    this.credential = new DefaultAzureCredential({
      tenantId,
      // managedIdentityClientId: clientId, // only if using user-assigned identity
    });
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
