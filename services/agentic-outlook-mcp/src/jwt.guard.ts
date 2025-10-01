import { OpaqueTokenService, TokenValidationResult } from '@unique-ag/mcp-oauth';
import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import { Request } from 'express';

export interface JwtAuthenticatedRequest extends Request {
  user?: TokenValidationResult;
}

@Injectable()
export class JwtGuard implements CanActivate {
  public constructor(private readonly tokenService: OpaqueTokenService) {}

  public async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<JwtAuthenticatedRequest>();

    const token = this.extractTokenFromHeader(request);
    if (!token) throw new UnauthorizedException('Access token required');

    const validationResult = await this.tokenService.validateAccessToken(token);
    if (!validationResult) throw new UnauthorizedException('Invalid or expired access token');

    request.user = validationResult;
    return true;
  }

  private extractTokenFromHeader(request: Request): string | undefined {
    const authHeader = request.headers.authorization;
    if (!authHeader) return undefined;

    const [type, token] = authHeader.split(' ');
    return type === 'Bearer' ? token : undefined;
  }
}
