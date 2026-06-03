import { describe, expect, it } from 'vitest';
import { AuthMode } from '../../../../config/confluence.schema';
import type { TenantContext } from '../../../../tenant/tenant-context.interface';
import { tenantStorage } from '../../../../tenant/tenant-context.storage';
import { Redacted } from '../../../../utils/redacted';
import { BasicAuthStrategy } from '../basic-auth.strategy';

const mockTenant: TenantContext = {
  name: 'test-tenant',
  config: {} as TenantContext['config'],
  status: 'active',
  isScanning: false,
};

describe('BasicAuthStrategy', () => {
  it('returns a Basic authorization header with base64(user:password)', async () => {
    const strategy = new BasicAuthStrategy({
      mode: AuthMode.Basic,
      username: 'alice',
      password: new Redacted('s3cret'),
    });

    const result = await tenantStorage.run(mockTenant, () => strategy.getAuthorizationHeader());

    expect(result).toBe(`Basic ${Buffer.from('alice:s3cret', 'utf8').toString('base64')}`);
  });

  it('returns the same header on multiple calls', async () => {
    const strategy = new BasicAuthStrategy({
      mode: AuthMode.Basic,
      username: 'bob',
      password: new Redacted('p@ssw0rd'),
    });

    const first = await tenantStorage.run(mockTenant, () => strategy.getAuthorizationHeader());
    const second = await tenantStorage.run(mockTenant, () => strategy.getAuthorizationHeader());

    expect(first).toBe(second);
  });

  it('correctly encodes credentials containing non-ASCII characters', async () => {
    const strategy = new BasicAuthStrategy({
      mode: AuthMode.Basic,
      username: 'üser',
      password: new Redacted('päss:wörd'),
    });

    const result = await tenantStorage.run(mockTenant, () => strategy.getAuthorizationHeader());

    const expected = Buffer.from('üser:päss:wörd', 'utf8').toString('base64');
    expect(result).toBe(`Basic ${expected}`);
  });
});
