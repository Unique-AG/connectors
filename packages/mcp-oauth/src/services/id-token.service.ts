import { Injectable, Logger } from '@nestjs/common';
import { importPKCS8, importSPKI, jwtVerify, SignJWT } from 'jose';
import { JWKSService } from './jwks.service';

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
  issuer: string;
  expiresIn: number;
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

  public constructor(private readonly jwksService: JWKSService) {}

  /**
   * Generates a JWT ID token for OIDC compliance using ECDSA
   * @param options Token generation options
   * @returns Signed JWT ID token
   */
  public async generateIDToken(options: IDTokenGenerationOptions): Promise<string> {
    if (!this.jwksService.isJWTEnabled()) {
      throw new Error('JWT signing is not configured');
    }

    const keys = await this.jwksService.getSigningKeys();

    try {
      const privateKey = await importPKCS8(keys.privateKey, keys.algorithm);

      // Build the payload with all custom claims
      const payload: Record<string, unknown> = {
        azp: options.clientId,
      };

      if (options.nonce) payload.nonce = options.nonce;
      if (options.authTime) payload.auth_time = Math.floor(options.authTime / 1000);

      const scopes = options.scope?.split(' ') || [];

      if (scopes.includes('profile') && options.userProfile) {
        if (options.userProfile.displayName) payload.name = options.userProfile.displayName;
        if (options.userProfile.username) payload.preferred_username = options.userProfile.username;
        if (options.userProfile.avatarUrl) payload.picture = options.userProfile.avatarUrl;
      }

      if (scopes.includes('email') && options.userProfile?.email) {
        payload.email = options.userProfile.email;
        payload.email_verified = options.userProfile.emailVerified ?? false;
      }

      const jwtBuilder = new SignJWT(payload);

      // Add standard claims
      jwtBuilder
        .setProtectedHeader({
          alg: keys.algorithm,
          typ: 'JWT',
          kid: keys.keyId,
        })
        .setIssuer(options.issuer)
        .setSubject(options.userId)
        .setAudience(options.clientId)
        .setExpirationTime(`${options.expiresIn}s`)
        .setIssuedAt();

      const idToken = await jwtBuilder.sign(privateKey);

      this.logger.debug({
        msg: 'Generated ID token',
        userId: options.userId,
        clientId: options.clientId,
        scopes: scopes.join(' '),
        algorithm: keys.algorithm,
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
   * Validates a JWT ID token using ECDSA and jose
   * @param token The JWT ID token to validate
   * @param expectedIssuer The expected issuer for validation
   * @returns The decoded token claims or null if invalid
   */
  public async validateIDToken(
    token: string,
    expectedIssuer: string,
  ): Promise<IDTokenClaims | null> {
    if (!this.jwksService.isJWTEnabled()) {
      return null;
    }

    try {
      const keys = await this.jwksService.getSigningKeys();

      // Import the public key using jose
      const publicKey = await importSPKI(keys.publicKey, keys.algorithm);

      // Verify the JWT using jose
      const { payload } = await jwtVerify(token, publicKey, {
        algorithms: [keys.algorithm],
        issuer: expectedIssuer,
      });

      // Map payload to our claims interface
      return payload as unknown as IDTokenClaims;
    } catch (error) {
      this.logger.debug({
        msg: 'ID token validation failed',
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      return null;
    }
  }
}
