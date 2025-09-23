import { Inject, Injectable, Logger } from '@nestjs/common';
import * as jwt from 'jsonwebtoken';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';

export interface IDTokenClaims {
  // Standard OIDC claims
  iss: string; // Issuer
  sub: string; // Subject (user ID)
  aud: string; // Audience (client ID)
  exp: number; // Expiration time
  iat: number; // Issued at
  auth_time?: number; // Authentication time
  nonce?: string; // Nonce from authorization request
  acr?: string; // Authentication Context Class Reference
  amr?: string[]; // Authentication Methods References
  azp?: string; // Authorized party (client ID)
  
  // User claims (when profile scope is requested)
  name?: string;
  given_name?: string;
  family_name?: string;
  middle_name?: string;
  nickname?: string;
  preferred_username?: string;
  profile?: string;
  picture?: string;
  website?: string;
  email?: string;
  email_verified?: boolean;
  gender?: string;
  birthdate?: string;
  zoneinfo?: string;
  locale?: string;
  phone_number?: string;
  phone_number_verified?: boolean;
  address?: {
    formatted?: string;
    street_address?: string;
    locality?: string;
    region?: string;
    postal_code?: string;
    country?: string;
  };
  updated_at?: number;
}

export interface IDTokenGenerationOptions {
  userId: string;
  clientId: string;
  nonce?: string;
  authTime?: number;
  scope?: string;
  userProfile?: {
    username?: string;
    email?: string;
    displayName?: string;
    avatarUrl?: string;
    emailVerified?: boolean;
  };
}

@Injectable()
export class IDTokenService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
  ) {}

  /**
   * Generates a JWT ID token for OIDC compliance
   * @param options Token generation options
   * @returns Signed JWT ID token
   */
  public generateIDToken(options: IDTokenGenerationOptions): string {
    const now = Math.floor(Date.now() / 1000);
    const expiresIn = this.options.idTokenExpiresIn || 3600;

    const claims: IDTokenClaims = {
      iss: this.options.serverUrl,
      sub: options.userId,
      aud: options.clientId,
      exp: now + expiresIn,
      iat: now,
      azp: options.clientId,
    };

    if (options.nonce) claims.nonce = options.nonce;
    if (options.authTime) claims.auth_time = Math.floor(options.authTime / 1000);

    const scopes = options.scope?.split(' ') || [];

    if (scopes.includes('profile') && options.userProfile) {
      if (options.userProfile.displayName) claims.name = options.userProfile.displayName;
      if (options.userProfile.username) claims.preferred_username = options.userProfile.username;
      if (options.userProfile.avatarUrl) claims.picture = options.userProfile.avatarUrl;
    }

    if (scopes.includes('email') && options.userProfile?.email) {
      claims.email = options.userProfile.email;
      if (options.userProfile.emailVerified) claims.email_verified = options.userProfile.emailVerified ?? false;
    }

    const signingKey = this.options.jwtSigningKey || this.options.hmacSecret;
    const algorithm = this.options.jwtSigningAlgorithm || 'HS256';

    try {
      const idToken = jwt.sign(claims, signingKey, {
        algorithm,
        header: {
          typ: 'JWT',
          alg: algorithm,
          kid: 'default',
        },
      });

      this.logger.debug({
        msg: 'Generated ID token',
        userId: options.userId,
        clientId: options.clientId,
        scopes: scopes.join(' '),
      });

      return idToken;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to generate ID token',
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      throw new Error('Failed to generate ID token');
    }
  }

  /**
   * Validates a JWT ID token
   * @param token The JWT ID token to validate
   * @returns The decoded token claims or null if invalid
   */
  public validateIDToken(token: string): IDTokenClaims | null {
    try {
      const signingKey = this.options.jwtSigningKey || this.options.hmacSecret;
      const algorithm = this.options.jwtSigningAlgorithm || 'HS256';

      const decoded = jwt.verify(token, signingKey, {
        algorithms: [algorithm as jwt.Algorithm],
        issuer: this.options.serverUrl,
      }) as IDTokenClaims;

      return decoded;
    } catch (error) {
      this.logger.debug({
        msg: 'ID token validation failed',
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      return null;
    }
  }
}
