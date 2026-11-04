import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { Inject, Injectable, OnModuleDestroy } from '@nestjs/common';
import { type McpRateLimitConfig } from '../config/rate-limit.config';
import { type HttpRequest, type McpOptions } from '../interfaces';

/** The consumer's `McpRateLimitConfig`, aliased from the token in `McpOptions.rateLimit`. */
export const MCP_RATE_LIMIT_CONFIG = Symbol('MCP_RATE_LIMIT_CONFIG');

interface ActiveLimit {
  toolCallsPerWindow: number;
  windowMs: number;
  getRequestKey: (request: HttpRequest) => string;
}

@Injectable()
export class RateLimiterService implements OnModuleDestroy {
  private readonly buckets = new Map<string, number[]>();
  private readonly limit: ActiveLimit | undefined;
  private readonly cleanupTimer: ReturnType<typeof setInterval> | undefined;

  public constructor(
    @Inject('MCP_OPTIONS') options: McpOptions,
    @Inject(MCP_RATE_LIMIT_CONFIG) config: McpRateLimitConfig | null,
  ) {
    if (!options.rateLimit || !config || config.toolCallsPerWindow === 0) {
      return;
    }

    this.limit = {
      toolCallsPerWindow: config.toolCallsPerWindow,
      windowMs: config.windowSeconds * 1000,
      getRequestKey: options.rateLimit.getRequestKey,
    };
    this.cleanupTimer = setInterval(() => this.cleanup(), this.limit.windowMs);
    this.cleanupTimer.unref();
  }

  public onModuleDestroy(): void {
    clearInterval(this.cleanupTimer);
  }

  public check(request: HttpRequest): void {
    if (!this.limit) {
      return;
    }

    const key = this.limit.getRequestKey(request);
    const now = Date.now();
    const windowStart = now - this.limit.windowMs;
    const recent = (this.buckets.get(key) ?? []).filter((t) => t > windowStart);

    if (recent.length >= this.limit.toolCallsPerWindow) {
      throw new McpError(
        ErrorCode.InvalidRequest,
        `Rate limit exceeded: ${this.limit.toolCallsPerWindow} tool calls per ${Math.round(this.limit.windowMs / 1000)} seconds`,
      );
    }

    this.buckets.set(key, [...recent, now]);
  }

  private cleanup(): void {
    if (!this.limit) {
      return;
    }
    const windowStart = Date.now() - this.limit.windowMs;
    for (const [key, timestamps] of this.buckets) {
      const recent = timestamps.filter((t) => t > windowStart);
      if (recent.length === 0) {
        this.buckets.delete(key);
      } else {
        this.buckets.set(key, recent);
      }
    }
  }
}
