import {
  CanActivate,
  ExecutionContext,
  Inject,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { Request } from 'express';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';
import { OpaqueTokenService, type TokenValidationResult } from '../services/opaque-token.service';

export interface McpAuthenticatedRequest extends Request {
  user?: TokenValidationResult;
}

@Injectable()
export class McpAuthJwtGuard implements CanActivate {
  public constructor(
    private readonly tokenService: OpaqueTokenService,
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
  ) {}

  public async canActivate(context: ExecutionContext): Promise<boolean> {
    // We run the guard only on HTTP contexts (e.g. not on RabbitMQ contexts)
    if (context.getType() !== 'http') return true;

    const request = context.switchToHttp().getRequest<McpAuthenticatedRequest>();

    // This is a global guard, as we cannot inject it into the McpModule
    // To not interfere with authentication and other routes, we only authenticate requests to /mcp endpoints
    if (!request.url.startsWith('/mcp/') && request.url !== '/mcp') return true;

    const token = this.extractTokenFromHeader(request);
    if (!token) throw new UnauthorizedException('Access token required');

    const validationResult = await this.tokenService.validateAccessToken(token);
    if (!validationResult) throw new UnauthorizedException('Invalid or expired access token');

    // Validate that the token was issued for this specific MCP server resource
    // This prevents token passthrough attacks as required by the MCP specification
    if (validationResult.resource !== this.options.resource)
      throw new UnauthorizedException(
        'Token not valid for this resource. Token was issued for a different resource.',
      );

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
