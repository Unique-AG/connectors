import { type ExecutionContext, Inject, Injectable } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import {
  InjectThrottlerOptions,
  InjectThrottlerStorage,
  ThrottlerGuard,
  type ThrottlerModuleOptions,
  type ThrottlerStorage,
} from '@nestjs/throttler';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';

/**
 * The throttler guard for every OAuth route, with an emergency switch. `disableRateLimiting`
 * lets an operator rule rate limiting in or out of an incident with a config change instead of
 * a release.
 */
@Injectable()
export class McpOAuthThrottlerGuard extends ThrottlerGuard {
  public constructor(
    @InjectThrottlerOptions() options: ThrottlerModuleOptions,
    @InjectThrottlerStorage() storageService: ThrottlerStorage,
    reflector: Reflector,
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly moduleOptions: McpOAuthModuleOptions,
  ) {
    super(options, storageService, reflector);
  }

  protected override async shouldSkip(_context: ExecutionContext): Promise<boolean> {
    return this.moduleOptions.disableRateLimiting;
  }
}
