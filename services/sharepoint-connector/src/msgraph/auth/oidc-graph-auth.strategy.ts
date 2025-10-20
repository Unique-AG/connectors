import { DefaultAzureCredential } from '@azure/identity';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { serializeError } from 'serialize-error-cjs';
import { z } from 'zod';
import { Config } from '../../config';
import { normalizeError } from '../../utils/normalize-error';
import { GraphAuthStrategy } from './graph-auth-strategy.interface';

interface CachedToken {
  accessToken: string;
  expiresAt: number;
}

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
  private cachedToken: CachedToken | null = null;

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const tenantId = this.configService.get('sharepoint.graphTenantId', { infer: true });
    // const clientId = this.configService.get('sharepoint.graphClientId', { infer: true });

    this.credential = new DefaultAzureCredential({
      tenantId,
      // managedIdentityClientId: clientId, // only if using user-assigned identity
    });
  }

  public async getAccessToken(scope: string): Promise<string> {
    if (this.cachedToken && this.isTokenValid(this.cachedToken)) {
      return this.cachedToken.accessToken;
    }

    return await this.acquireNewToken(scope);
  }

  private isTokenValid(token: CachedToken): boolean {
    const now = Date.now();
    return token.expiresAt > now;
  }

  private async acquireNewToken(scope: string): Promise<string> {
    try {
      const tokenResponse = await this.credential.getToken(scope);
      const validatedResponse = TokenResponseSchema.parse(tokenResponse);

      this.cachedToken = {
        accessToken: validatedResponse.token,
        expiresAt: validatedResponse.expiresOnTimestamp,
      };

      return validatedResponse.token;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to acquire Graph API token using OIDC',
        error: serializeError(normalizeError(error)),
      });

      this.cachedToken = null;
      throw error;
    }
  }
}
