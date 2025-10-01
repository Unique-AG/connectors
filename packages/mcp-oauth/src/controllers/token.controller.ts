import {
  BadRequestException,
  Body,
  Controller,
  Header,
  HttpCode,
  HttpStatus,
  Logger,
  Post,
  UseGuards,
  UsePipes,
} from '@nestjs/common';
import { SkipThrottle, ThrottlerGuard } from '@nestjs/throttler';
import { ZodValidationPipe } from 'nestjs-zod';
import { OAUTH_ENDPOINTS } from '../constants/oauth.constants';
import { type IntrospectionResponse, IntrospectRequestDto } from '../dtos/introspect-request.dto';
import { RevokeRequestDto } from '../dtos/revoke-request.dto';
import { TokenRequestDto } from '../dtos/token-request.dto';
import { McpOAuthService } from '../services/mcp-oauth.service';

@Controller()
@UseGuards(ThrottlerGuard)
@UsePipes(ZodValidationPipe)
// FIXME: Remove this once we have a better way to throttle the token endpoint
@SkipThrottle()
export class TokenController {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly authService: McpOAuthService) {}

  @Post(OAUTH_ENDPOINTS.token)
  @Header('Cache-Control', 'no-store')
  @Header('Pragma', 'no-cache')
  @Header('X-Content-Type-Options', 'nosniff')
  @Header('X-Frame-Options', 'DENY')
  @Header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
  @HttpCode(HttpStatus.OK)
  public async token(@Body() tokenDto: TokenRequestDto) {
    this.logger.debug({
      msg: 'Token exchange request',
      grantType: tokenDto.grant_type,
    });

    switch (tokenDto.grant_type) {
      case 'authorization_code':
        return this.authService.exchangeAuthorizationCodeForToken(tokenDto);
      case 'refresh_token':
        return this.authService.exchangeRefreshTokenForToken(tokenDto);
      default:
        throw new BadRequestException(`Unsupported grant type ${tokenDto.grant_type}`);
    }
  }

  /**
   * Token introspection endpoint as defined in RFC 7662.
   * Allows authorized clients to query the status and metadata of tokens.
   */
  @Post(OAUTH_ENDPOINTS.introspect)
  @Header('Cache-Control', 'no-store')
  @Header('Pragma', 'no-cache')
  @Header('X-Content-Type-Options', 'nosniff')
  @Header('X-Frame-Options', 'DENY')
  @Header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
  @HttpCode(HttpStatus.OK)
  public async introspect(
    @Body() introspectDto: IntrospectRequestDto,
  ): Promise<IntrospectionResponse> {
    this.logger.debug({
      msg: 'Token introspection request',
      clientId: introspectDto.client_id,
      tokenTypeHint: introspectDto.token_type_hint,
    });

    try {
      return await this.authService.introspectToken(introspectDto);
    } catch (error) {
      // Per RFC 7662, we should not leak information about why introspection failed
      // Always return { active: false } for any error condition
      this.logger.error({
        msg: 'Token introspection failed',
        error: error instanceof Error ? error.message : 'Unknown error',
      });

      return { active: false };
    }
  }

  /**
   * Token revocation endpoint as defined in RFC 7009.
   * Allows clients to notify the authorization server that a token is no longer needed.
   */
  @Post(OAUTH_ENDPOINTS.revoke)
  @Header('Cache-Control', 'no-store')
  @Header('Pragma', 'no-cache')
  @Header('X-Content-Type-Options', 'nosniff')
  @Header('X-Frame-Options', 'DENY')
  @Header('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
  @HttpCode(HttpStatus.OK)
  public async revoke(@Body() revokeDto: RevokeRequestDto): Promise<void> {
    this.logger.debug({
      msg: 'Token revocation request',
      clientId: revokeDto.client_id,
      tokenTypeHint: revokeDto.token_type_hint,
    });

    try {
      await this.authService.revokeToken(revokeDto);
    } catch (error) {
      // Per RFC 7009, the revocation endpoint should not indicate error conditions
      // to prevent information leakage about token existence
      this.logger.error({
        msg: 'Token revocation failed',
        error: error instanceof Error ? error.message : 'Unknown error',
      });
    }

    // Always return 200 OK regardless of outcome
    return;
  }
}
