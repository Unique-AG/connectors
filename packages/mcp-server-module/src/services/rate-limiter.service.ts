import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { OnModuleDestroy } from '@nestjs/common';
import { type McpRateLimitConfig } from '../config/rate-limit.config';
import { type HttpRequest } from '../interfaces';

/** The server's `RateLimiterService`, or `null` when it configures no `rateLimit`. */
export const MCP_RATE_LIMITER = Symbol('MCP_RATE_LIMITER');

export class RateLimiterService implements OnModuleDestroy {
  private readonly buckets = new Map<string, number[]>();
  private readonly cleanupTimer: ReturnType<typeof setInterval>;

  private readonly toolCallsPerWindow: number;
  private readonly windowMs: number;

  public constructor(
    config: McpRateLimitConfig,
    private readonly getRequestKey: (request: HttpRequest) => string,
  ) {
    this.toolCallsPerWindow = config.toolCallsPerWindow;
    this.windowMs = config.windowSeconds * 1000;
    this.cleanupTimer = setInterval(() => this.cleanup(), this.windowMs);
    this.cleanupTimer.unref();
  }

  public onModuleDestroy(): void {
    clearInterval(this.cleanupTimer);
  }

  public check(request: HttpRequest): void {
    const key = this.getRequestKey(request);
    const now = Date.now();
    const recent = (this.buckets.get(key) ?? []).filter((t) => t > now - this.windowMs);

    if (recent.length >= this.toolCallsPerWindow) {
      throw new McpError(
        ErrorCode.InvalidRequest,
        `Rate limit exceeded: ${this.toolCallsPerWindow} tool calls per ${Math.round(this.windowMs / 1000)} seconds`,
      );
    }

    this.buckets.set(key, [...recent, now]);
  }

  private cleanup(): void {
    const windowStart = Date.now() - this.windowMs;
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
