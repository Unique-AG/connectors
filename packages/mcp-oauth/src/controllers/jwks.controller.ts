import { Controller, Get, Header, UseGuards } from '@nestjs/common';
import { SkipThrottle, ThrottlerGuard } from '@nestjs/throttler';
import { type JWKSet, JWKSService } from '../services/jwks.service';

/**
 * JWKS (JSON Web Key Set) Controller
 * Provides public keys for JWT validation according to RFC 7517
 */
@Controller('.well-known')
@UseGuards(ThrottlerGuard)
@SkipThrottle()
export class JWKSController {
  public constructor(private readonly jwksService: JWKSService) {}

  /**
   * JWKS endpoint as defined in RFC 7517
   * Returns the public keys used to sign JWTs (ID tokens and JWT access tokens)
   *
   * This endpoint is typically cached by clients for efficient token validation.
   * The Cache-Control header is set to allow caching for 1 hour.
   */
  @Get('jwks.json')
  @Header('Content-Type', 'application/json')
  @Header('Cache-Control', 'public, max-age=3600, s-maxage=3600')
  @Header('X-Content-Type-Options', 'nosniff')
  @Header('X-Frame-Options', 'DENY')
  public async getJWKS(): Promise<JWKSet> {
    if (!this.jwksService.isJWTEnabled()) {
      // Return empty key set if JWT is not configured
      return { keys: [] };
    }

    return await this.jwksService.getJWKSet();
  }
}
