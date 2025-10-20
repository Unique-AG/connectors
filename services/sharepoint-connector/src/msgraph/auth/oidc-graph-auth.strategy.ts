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
  private cachedToken: Record<string, CachedToken> = {};

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const tenantId = this.configService.get('sharepoint.graphTenantId', { infer: true });
    // const clientId = this.configService.get('sharepoint.graphClientId', { infer: true });

    this.credential = new DefaultAzureCredential({
      tenantId,
      // managedIdentityClientId: clientId, // only if using user-assigned identity
    });
  }

  public async getAccessToken(scope: string): Promise<string> {
    if (this.cachedToken[scope] && this.isTokenValid(this.cachedToken[scope])) {
      return this.cachedToken[scope].accessToken;
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

      this.cachedToken[scope] = {
        accessToken: validatedResponse.token,
        expiresAt: validatedResponse.expiresOnTimestamp,
      };

      this.logTokenInternalForDebugging(validatedResponse.token);
      return validatedResponse.token;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to acquire Graph API token using OIDC',
        error: serializeError(normalizeError(error)),
      });

      delete this.cachedToken[scope];
      throw error;
    }
  }

  // Purely for debugging the OIDC token that fail in an unexpcted way
  private logTokenInternalForDebugging(token: string): void {
    const parts = token.split('.');

    const b64urlToJson = (str: string): Record<string, unknown> => {
      const b64 = str.replace(/-/g, '+').replace(/_/g, '/');
      const buf = Buffer.from(b64, 'base64');
      try {
        return JSON.parse(buf.toString('utf8'));
      } catch {
        return {};
      }
    };

    const header = b64urlToJson(parts[0] ?? '');
    const payload = b64urlToJson(parts[1] ?? '');

    const tokenSafeProperties = {
      // Header
      alg: header.alg,
      kid: header.kid,
      typ: header.typ,

      // Issuance context
      iss: payload.iss,
      aud: payload.aud,
      tenantId: payload.tid,
      appId: payload.appid || payload.azp || payload.aio, // azp/appid vary by flow
      appDisplayName: payload.app_displayname,
      tokenUse: payload?.typ || 'access',

      // Permissions
      scopes: typeof payload.scp === 'string' ? payload.scp.split(' ') : undefined,
      roles: payload.roles,

      // Timing (convert to ISO for readability)
      iat: typeof payload.iat === 'number' ? new Date(payload.iat * 1000).toISOString() : undefined,
      nbf: typeof payload.nbf === 'number' ? new Date(payload.nbf * 1000).toISOString() : undefined,
      exp: typeof payload.exp === 'number' ? new Date(payload.exp * 1000).toISOString() : undefined,
    };

    this.logger.log(JSON.stringify(tokenSafeProperties, null, 4));
  }
}
