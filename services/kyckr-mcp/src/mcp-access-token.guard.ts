import { timingSafeEqual } from 'node:crypto';
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

    const provided = header.slice('Bearer '.length);
    if (!this.constantTimeEquals(provided, expected)) {
      this.logger.warn({ path: request.path }, 'Invalid MCP access token');
      return false;
    }

    return true;
  }

  private constantTimeEquals(a: string, b: string): boolean {
    const aBuf = Buffer.from(a, 'utf8');
    const bBuf = Buffer.from(b, 'utf8');
    // timingSafeEqual requires equal lengths; pad the shorter buffer and still compare
    // lengths at the end so mismatched-length inputs never short-circuit before the compare.
    const len = Math.max(aBuf.length, bBuf.length);
    const aPadded = Buffer.alloc(len);
    const bPadded = Buffer.alloc(len);
    aBuf.copy(aPadded);
    bBuf.copy(bPadded);
    return timingSafeEqual(aPadded, bPadded) && aBuf.length === bBuf.length;
  }

  private isMcpRoute(path: string): boolean {
    const lower = path.toLowerCase();
    return lower === '/mcp' || lower.startsWith('/mcp/');
  }
}
