import type { ExecutionContext } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { ThrottlerStorageService } from '@nestjs/throttler';
import { describe, expect, it } from 'vitest';
import type { McpOAuthModuleOptions } from '../mcp-oauth.module-definition';
import { McpOAuthThrottlerGuard } from './mcp-oauth-throttler.guard';

const context = {} as ExecutionContext;

function buildGuard(disableRateLimiting: boolean): McpOAuthThrottlerGuard {
  return new McpOAuthThrottlerGuard(
    { throttlers: [{ name: 'default', ttl: 60_000, limit: 10 }] },
    new ThrottlerStorageService(),
    new Reflector(),
    { disableRateLimiting } as McpOAuthModuleOptions,
  );
}

describe('McpOAuthThrottlerGuard', () => {
  it('applies the throttlers by default', async () => {
    // biome-ignore lint/suspicious/noExplicitAny: Call the protected hook ThrottlerGuard consults first
    const shouldSkip = (buildGuard(false) as any).shouldSkip.bind(buildGuard(false));

    await expect(shouldSkip(context)).resolves.toBe(false);
  });

  it('skips every throttler when rate limiting is disabled', async () => {
    const guard = buildGuard(true);
    // biome-ignore lint/suspicious/noExplicitAny: Call the protected hook ThrottlerGuard consults first
    const shouldSkip = (guard as any).shouldSkip.bind(guard);

    await expect(shouldSkip(context)).resolves.toBe(true);
  });
});
