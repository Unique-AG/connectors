import type { ExecutionContext } from '@nestjs/common';
import { UnauthorizedException } from '@nestjs/common';
import { describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../config/config.js';
import { KongIdentityGuard } from './identity.guard.js';

function context(headers: Record<string, string>): ExecutionContext {
  return {
    switchToHttp: () => ({ getRequest: () => ({ headers }) }),
  } as ExecutionContext;
}

describe('KongIdentityGuard', () => {
  it('rejects requests without every Kong identity header', () => {
    const guard = new KongIdentityGuard({ authMode: 'kong' } as GatewayConfig);

    expect(() =>
      guard.canActivate(
        context({ 'x-user-id': 'user', 'x-company-id': 'company', 'x-user-roles': 'role' }),
      ),
    ).toThrow(UnauthorizedException);
  });

  it('allows the explicit development mode', () => {
    const guard = new KongIdentityGuard({ authMode: 'development' } as GatewayConfig);

    expect(guard.canActivate(context({}))).toBe(true);
  });
});
