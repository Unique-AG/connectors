import type { ExecutionContext } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { seconds, ThrottlerException, ThrottlerStorageService } from '@nestjs/throttler';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { McpOAuthModuleOptions } from '../mcp-oauth.module-definition';
import { McpOAuthThrottlerGuard } from './mcp-oauth-throttler.guard';
import { PER_IP_CEILING_KEY } from './per-ip-ceiling.decorator';

class TestController {}

function buildContext(
  handler: (...args: unknown[]) => unknown,
  body: Record<string, unknown> = {},
): ExecutionContext {
  return {
    getHandler: () => handler,
    getClass: () => TestController,
    switchToHttp: () => ({
      getRequest: () => ({ ip: '203.0.113.10', headers: {}, body }),
      getResponse: () => ({ header: vi.fn() }),
    }),
  } as unknown as ExecutionContext;
}

describe('McpOAuthThrottlerGuard', () => {
  let storage: ThrottlerStorageService;

  beforeEach(() => {
    storage = new ThrottlerStorageService();
  });

  afterEach(() => {
    storage.onApplicationShutdown();
  });

  async function buildGuard(disableRateLimiting: boolean): Promise<McpOAuthThrottlerGuard> {
    const guard = new McpOAuthThrottlerGuard(
      { throttlers: [{ name: 'default', ttl: seconds(60), limit: 2 }] },
      storage,
      new Reflector(),
      { disableRateLimiting } as McpOAuthModuleOptions,
    );
    await guard.onModuleInit();
    return guard;
  }

  it('applies the default throttler to a plain route', async () => {
    const guard = await buildGuard(false);
    const context = buildContext(function plainRoute() {});

    await expect(guard.canActivate(context)).resolves.toBe(true);
    await expect(guard.canActivate(context)).resolves.toBe(true);
    await expect(guard.canActivate(context)).rejects.toBeInstanceOf(ThrottlerException);
  });

  it('allows everything and allocates nothing when rate limiting is disabled', async () => {
    const guard = await buildGuard(true);
    const context = buildContext(function plainRoute() {});

    for (let attempt = 0; attempt < 5; attempt++) {
      await expect(guard.canActivate(context)).resolves.toBe(true);
    }
    expect(storage.storage.size).toBe(0);
  });

  it('rejects at the per-IP ceiling before allocating a record for the route bucket', async () => {
    const guard = await buildGuard(false);
    function cappedRoute() {}
    Reflect.defineMetadata(PER_IP_CEILING_KEY, { limit: 1, ttl: seconds(60) }, cappedRoute);

    await expect(guard.canActivate(buildContext(cappedRoute))).resolves.toBe(true);
    const recordsAfterFirst = storage.storage.size;

    await expect(guard.canActivate(buildContext(cappedRoute))).rejects.toBeInstanceOf(
      ThrottlerException,
    );
    expect(storage.storage.size).toBe(recordsAfterFirst);
  });
});
