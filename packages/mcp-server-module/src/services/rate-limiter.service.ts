import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { Inject, Injectable, OnModuleDestroy } from '@nestjs/common';
import { type McpOptions } from '../interfaces';

const DEFAULT_CALLS_PER_WINDOW = 60;
const DEFAULT_WINDOW_MS = 60_000;

@Injectable()
export class RateLimiterService implements OnModuleDestroy {
  private readonly buckets = new Map<string, number[]>();
  private cleanupTimer: ReturnType<typeof setInterval> | undefined;

  public readonly toolCallsPerWindow: number;
  public readonly windowMs: number;
  public readonly enabled: boolean;

  public constructor(@Inject('MCP_OPTIONS') options: McpOptions) {
    this.toolCallsPerWindow = options.rateLimit?.toolCallsPerWindow ?? DEFAULT_CALLS_PER_WINDOW;
    this.windowMs = options.rateLimit?.windowMs ?? DEFAULT_WINDOW_MS;
    this.enabled = this.toolCallsPerWindow > 0;

    if (this.enabled) {
      this.cleanupTimer = setInterval(() => this.cleanup(), this.windowMs);
      this.cleanupTimer.unref();
    }
  }

  public onModuleDestroy(): void {
    clearInterval(this.cleanupTimer);
  }

  public check(userId: string): void {
    if (!this.enabled) {
      return;
    }

    const now = Date.now();
    const windowStart = now - this.windowMs;
    const prev = this.buckets.get(userId) ?? [];
    const recent = prev.filter((t) => t > windowStart);

    if (recent.length >= this.toolCallsPerWindow) {
      throw new McpError(
        ErrorCode.InvalidRequest,
        `Rate limit exceeded: ${this.toolCallsPerWindow} tool calls per ${Math.round(this.windowMs / 1000)} seconds`,
      );
    }

    this.buckets.set(userId, [...recent, now]);
  }

  private cleanup(): void {
    const windowStart = Date.now() - this.windowMs;
    for (const [userId, timestamps] of this.buckets) {
      const recent = timestamps.filter((t) => t > windowStart);
      if (recent.length === 0) {
        this.buckets.delete(userId);
      } else {
        this.buckets.set(userId, recent);
      }
    }
  }
}
