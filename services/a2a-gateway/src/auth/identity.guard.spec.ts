import type { ExecutionContext } from '@nestjs/common';
import { UnauthorizedException } from '@nestjs/common';
import { describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../config/config.js';
import { KongIdentityGuard } from './identity.guard.js';

function context(headers: Record<string, string | undefined>): ExecutionContext {
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

  it('accepts the standard trusted OAuth identity without a custom principal claim', () => {
    const guard = new KongIdentityGuard({ authMode: 'kong' } as GatewayConfig);
    const headers = {
      'x-user-id': 'user',
      'x-company-id': 'company',
      'x-client-id': 'client',
    };
    expect(guard.canActivate(context(headers))).toBe(true);
    for (const patch of [
      { 'x-service-id': 'service' },
      { 'x-user-id': ' ' },
      { 'x-client-id': '' },
    ]) {
      expect(() => guard.canActivate(context({ ...headers, ...patch }))).toThrow(
        UnauthorizedException,
      );
    }
  });

  it('allows the explicit development mode', () => {
    const guard = new KongIdentityGuard({ authMode: 'development' } as GatewayConfig);

    expect(guard.canActivate(context({}))).toBe(true);
  });
});
