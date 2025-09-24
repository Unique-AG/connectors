import { Injectable, Logger } from '@nestjs/common';
import { decodeJwt, importPKCS8, importSPKI, jwtVerify, SignJWT } from 'jose';
import * as z from 'zod';
import { JWKSService } from './jwks.service';

export interface JWTAccessTokenClaims {
  iss: string; // Issuer
  sub: string; // Subject (user ID)
  aud: string | string[]; // Audience (resource server)
  exp: number; // Expiration time
  iat: number; // Issued at
  jti: string; // JWT ID
  client_id: string; // OAuth client ID
  scope?: string; // OAuth scopes
  azp?: string; // Authorized party (client ID)

  // Custom claims for MCP
  resource?: string;
  user_profile_id?: string;
}

export interface JWTAccessTokenOptions {
  userId: string;
  clientId: string;
  scope?: string;
  resource: string;
  userProfileId: string;
  expiresIn: number;
  tokenId: string;
  issuer: string;
}

const JWTAccessTokenClaimsSchema = z.object({
  // Required standard JWT claims
  iss: z.string(),
  sub: z.string(),
  aud: z.union([z.string(), z.array(z.string())]),
  exp: z.number(),
  iat: z.number(),
  jti: z.string(),

  // Required OAuth/custom claims
  client_id: z.string(),

  // Optional claims
  scope: z.string().optional(),
  azp: z.string().optional(),
  resource: z.string().optional(),
  user_profile_id: z.string().optional(),
});

@Injectable()
export class JWTAccessTokenService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly jwksService: JWKSService) {}

  public async generateAccessToken(options: JWTAccessTokenOptions): Promise<string> {
    if (!this.jwksService.isJWTEnabled()) {
      throw new Error('JWT signing is not configured');
    }

    const keys = await this.jwksService.getSigningKeys();

    try {
      const privateKey = await importPKCS8(keys.privateKey, keys.algorithm);

      const jwt = await new SignJWT({
        client_id: options.clientId,
        azp: options.clientId,
        scope: options.scope,
        resource: options.resource,
        user_profile_id: options.userProfileId,
      })
        .setProtectedHeader({
          alg: keys.algorithm,
          typ: 'at+jwt', // RFC 9068: JWT Access Token type
          kid: keys.keyId,
        })
        .setIssuer(options.issuer)
        .setSubject(options.userId)
        .setAudience(options.resource)
        .setJti(options.tokenId)
        .setExpirationTime(`${options.expiresIn}s`)
        .setIssuedAt()
        .sign(privateKey);

      this.logger.debug({
        msg: 'Generated JWT access token',
        userId: options.userId,
        clientId: options.clientId,
        tokenId: options.tokenId,
        algorithm: keys.algorithm,
      });

      return jwt;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to generate JWT access token',
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      throw new Error('Failed to generate JWT access token');
    }
  }

  public async validateAccessToken(
    token: string,
    expectedResource?: string,
  ): Promise<JWTAccessTokenClaims | null> {
    if (!this.jwksService.isJWTEnabled()) {
      return null;
    }

    try {
      const keys = await this.jwksService.getSigningKeys();

      const publicKey = await importSPKI(keys.publicKey, keys.algorithm);

      const { payload } = await jwtVerify(token, publicKey, {
        algorithms: [keys.algorithm],
        audience: expectedResource,
      });

      return JWTAccessTokenClaimsSchema.parse(payload);
    } catch (error) {
      this.logger.debug({
        msg: 'JWT access token validation failed',
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      return null;
    }
  }

  public decodeAccessToken(token: string): JWTAccessTokenClaims | null {
    try {
      const payload = decodeJwt(token);
      return JWTAccessTokenClaimsSchema.parse(payload);
    } catch (error) {
      this.logger.debug({
        msg: 'Failed to decode JWT access token',
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      return null;
    }
  }
}
