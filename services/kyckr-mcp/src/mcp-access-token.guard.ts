import { CanActivate, ExecutionContext, Inject, Injectable, Logger } from '@nestjs/common';
import type { Request } from 'express';
import { type AppConfig, appConfig } from '~/config';

@Injectable()
export class McpAccessTokenGuard implements CanActivate {
  private readonly logger = new Logger(McpAccessTokenGuard.name);

  public constructor(
    @Inject(appConfig.KEY)
    private readonly config: AppConfig,
  ) {}

  public canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest<Request>();
    if (!this.isMcpRoute(request.path)) {
      return true;
    }

    const expected = this.config.mcpAccessToken.value;
    const header = request.headers.authorization;
    if (typeof header !== 'string' || !header.startsWith('Bearer ')) {
      this.logger.warn({ path: request.path }, 'Missing or malformed Authorization header on /mcp');
      return false;
    }

    if (header.slice('Bearer '.length) !== expected) {
      this.logger.warn({ path: request.path }, 'Invalid MCP access token');
      return false;
    }

    return true;
  }

  private isMcpRoute(path: string): boolean {
    const lower = path.toLowerCase();
    return lower === '/mcp' || lower.startsWith('/mcp/');
  }
}
