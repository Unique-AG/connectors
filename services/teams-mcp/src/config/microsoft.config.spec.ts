import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { microsoftConfig } from './microsoft.config';

const TENANT = 'd050ee55-f842-4802-8263-d802dc017162';
const ANOTHER_TENANT = '79a9ddfe-a4f3-4307-8086-471132901889';

describe('microsoft.allowedTenantIds', () => {
  beforeEach(() => {
    vi.stubEnv('MICROSOFT_CLIENT_ID', 'c4b2a7d1-5e3f-4a6b-9c8d-0e1f2a3b4c5d');
    vi.stubEnv('MICROSOFT_CLIENT_SECRET', 'client-secret');
    vi.stubEnv('MICROSOFT_WEBHOOK_SECRET', 'w'.repeat(128));
    vi.stubEnv('MICROSOFT_PUBLIC_WEBHOOK_URL', 'https://mcp.example.com');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each([
    ['unset', undefined, []],
    ['empty', '', []],
    ['one tenant', TENANT, [TENANT]],
    ['several tenants', `${TENANT},${ANOTHER_TENANT}`, [TENANT, ANOTHER_TENANT]],
    ['padded entries', `  ${TENANT} , ${ANOTHER_TENANT}  `, [TENANT, ANOTHER_TENANT]],
    ['an upper-case tenant', TENANT.toUpperCase(), [TENANT]],
  ])('reads %s from MICROSOFT_ALLOWED_TENANT_IDS', async (_case, written, allowed) => {
    vi.stubEnv('MICROSOFT_ALLOWED_TENANT_IDS', written);

    const config = await microsoftConfig();

    expect(config.allowedTenantIds).toEqual(allowed);
  });

  it('rejects an entry that is not a tenant GUID', async () => {
    vi.stubEnv('MICROSOFT_ALLOWED_TENANT_IDS', `${TENANT},contoso.onmicrosoft.com`);

    await expect(microsoftConfig()).rejects.toThrow('Invalid GUID');
  });
});
