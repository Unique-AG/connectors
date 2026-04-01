import { describe, expect, it } from 'vitest';
import { buildExternalId, parseExternalId } from '../external-id';

describe('parseExternalId', () => {
  it('parses a valid external id with all four segments', () => {
    const result = parseExternalId('confc:my-tenant:space-123:ENG');

    expect(result).toEqual({
      tenantName: 'my-tenant',
      spaceId: 'space-123',
      spaceKey: 'ENG',
    });
  });

  it('returns undefined for undefined input', () => {
    expect(parseExternalId(undefined)).toBeUndefined();
  });

  it('returns undefined for empty string', () => {
    expect(parseExternalId('')).toBeUndefined();
  });

  it('returns undefined for wrong prefix', () => {
    expect(parseExternalId('wrong:my-tenant:space-123:ENG')).toBeUndefined();
  });

  it('returns undefined for old format with only 2 segments after prefix', () => {
    expect(parseExternalId('confc:my-tenant:ENG')).toBeUndefined();
  });

  it('returns undefined for too many segments after prefix', () => {
    expect(parseExternalId('confc:my-tenant:space-123:ENG:extra')).toBeUndefined();
  });
});

describe('buildExternalId', () => {
  it('builds the canonical external id string', () => {
    const result = buildExternalId('my-tenant', 'space-123', 'ENG');

    expect(result).toBe('confc:my-tenant:space-123:ENG');
  });

  it('produces a value that parseExternalId round-trips', () => {
    const externalId = buildExternalId('dogfood-cloud', 'abc-456', 'MKT');
    const parsed = parseExternalId(externalId);

    expect(parsed).toEqual({
      tenantName: 'dogfood-cloud',
      spaceId: 'abc-456',
      spaceKey: 'MKT',
    });
  });
});
