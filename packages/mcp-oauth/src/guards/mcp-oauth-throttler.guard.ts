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
import {
  PER_IP_CEILING_KEY,
  PER_IP_CEILING_NAME,
  type PerIpCeilingOptions,
} from './per-ip-ceiling.decorator';

/**
 * The throttler guard for every OAuth route. `disableRateLimiting` skips it all without a
 * release, and `PerIpCeiling` adds a per-IP cap to a route whose bucket is per credential.
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

  public override async canActivate(context: ExecutionContext): Promise<boolean> {
    if (this.moduleOptions.disableRateLimiting) {
      return true;
    }
    // The ceiling runs first so a request it rejects allocates no per-credential record.
    const ceiling = this.reflector.getAllAndOverride<PerIpCeilingOptions | undefined>(
      PER_IP_CEILING_KEY,
      [context.getHandler(), context.getClass()],
    );
    if (ceiling) {
      await this.enforceCeiling(context, ceiling);
    }
    return super.canActivate(context);
  }

  private async enforceCeiling(
    context: ExecutionContext,
    ceiling: PerIpCeilingOptions,
  ): Promise<void> {
    const { req, res } = this.getRequestResponse(context);
    const tracker = await this.getTracker(req);
    const key = this.generateKey(context, tracker, PER_IP_CEILING_NAME);
    const record = await this.storageService.increment(
      key,
      ceiling.ttl,
      ceiling.limit,
      ceiling.ttl,
      PER_IP_CEILING_NAME,
    );
    if (record.isBlocked) {
      this.setResponseHeader(res, 'Retry-After', record.timeToBlockExpire);
      await this.throwThrottlingException(context, {
        ...record,
        ttl: ceiling.ttl,
        limit: ceiling.limit,
        key,
        tracker,
      });
    }
  }
}
