import { describe, expect, it } from 'vitest';
import type { ExecutionContext } from '@nestjs/common';
import { getMcpIdentity } from './get-mcp-identity';
import { McpIdentityResolver } from './mcp-identity-resolver.service';

describe('McpIdentityResolver', () => {
  function makeResolver(user: unknown) {
    // biome-ignore lint/suspicious/noExplicitAny: construct service with mock request for testing
    return new McpIdentityResolver({ user } as any);
  }

  it('returns null when request has no user', () => {
    const resolver = makeResolver(undefined);
    expect(resolver.resolve()).toBeNull();
  });

  it('builds identity from token validation result', () => {
    const resolver = makeResolver({
      userId: 'u1',
      clientId: 'c1',
      scope: 'mail.read mail.send',
      resource: 'https://api.example.com',
      userProfileId: 'p1',
      userData: { email: 'user@example.com', displayName: 'Test User' },
    });
    const identity = resolver.resolve();
    expect(identity).not.toBeNull();
    expect(identity?.userId).toBe('u1');
    expect(identity?.clientId).toBe('c1');
    expect(identity?.profileId).toBe('p1');
    expect(identity?.scopes).toEqual(['mail.read', 'mail.send']);
    expect(identity?.email).toBe('user@example.com');
    expect(identity?.displayName).toBe('Test User');
    expect(identity?.resource).toBe('https://api.example.com');
  });

  it('falls back to sub when userId is absent', () => {
    const resolver = makeResolver({ sub: 'sub-123', scope: '' });
    expect(resolver.resolve()?.userId).toBe('sub-123');
  });

  it('produces empty scopes array for empty scope string', () => {
    const resolver = makeResolver({ userId: 'u1', scope: '' });
    expect(resolver.resolve()?.scopes).toEqual([]);
  });

  it('handles missing userData gracefully', () => {
    const resolver = makeResolver({ userId: 'u1', scope: 'read' });
    const identity = resolver.resolve();
    expect(identity?.email).toBeUndefined();
    expect(identity?.displayName).toBeUndefined();
  });

  it('preserves raw token in raw field', () => {
    const rawToken = { userId: 'u1', scope: 'read', customField: 'value' };
    const resolver = makeResolver(rawToken);
    expect(resolver.resolve()?.raw).toBe(rawToken);
  });
});

describe('getMcpIdentity', () => {
  it('returns null for any context (stub pending CORE-009)', () => {
    const fakeCtx = {} as ExecutionContext;
    expect(getMcpIdentity(fakeCtx)).toBeNull();
  });
});
