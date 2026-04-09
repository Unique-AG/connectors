import { describe, expect, it } from 'vitest';
import { buildPartialContentKey, buildScopeExternalId, parseScopeExternalId } from '../key-format';

describe('parseScopeExternalId', () => {
  it('parses a valid external id with all four segments', () => {
    const result = parseScopeExternalId('confc:my-tenant:space-123:ENG');

    expect(result).toEqual({
      tenantName: 'my-tenant',
      spaceId: 'space-123',
      spaceKey: 'ENG',
    });
  });

  it('returns undefined for undefined input', () => {
    expect(parseScopeExternalId(undefined)).toBeUndefined();
  });

  it('returns undefined for empty string', () => {
    expect(parseScopeExternalId('')).toBeUndefined();
  });

  it('returns undefined for wrong prefix', () => {
    expect(parseScopeExternalId('wrong:my-tenant:space-123:ENG')).toBeUndefined();
  });

  it('returns undefined for old format with only 2 segments after prefix', () => {
    expect(parseScopeExternalId('confc:my-tenant:ENG')).toBeUndefined();
  });

  it('returns undefined for too many segments after prefix', () => {
    expect(parseScopeExternalId('confc:my-tenant:space-123:ENG:extra')).toBeUndefined();
  });
});

describe('buildScopeExternalId', () => {
  it('builds the canonical external id string', () => {
    const result = buildScopeExternalId('my-tenant', 'space-123', 'ENG');

    expect(result).toBe('confc:my-tenant:space-123:ENG');
  });

  it('produces a value that parseScopeExternalId round-trips', () => {
    const externalId = buildScopeExternalId('dogfood-cloud', 'abc-456', 'MKT');
    const parsed = parseScopeExternalId(externalId);

    expect(parsed).toEqual({
      tenantName: 'dogfood-cloud',
      spaceId: 'abc-456',
      spaceKey: 'MKT',
    });
  });
});

describe('buildPartialContentKey', () => {
  it('returns base key without tenant prefix for V1 format', () => {
    const result = buildPartialContentKey('my-tenant', 'space-123', 'ENG', true);

    expect(result).toBe('space-123_ENG');
  });

  it('returns key with tenant prefix for V2 format', () => {
    const result = buildPartialContentKey('my-tenant', 'space-123', 'ENG', false);

    expect(result).toBe('my-tenant/space-123_ENG');
  });
});
