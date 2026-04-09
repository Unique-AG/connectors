import { describe, expect, it } from 'vitest';
import { buildRootScopeExternalId, buildSpaceScopeExternalId } from '../ingestion.constants';

describe('buildRootScopeExternalId', () => {
  it('returns confc:cloud:<id> for cloud instances', () => {
    expect(buildRootScopeExternalId('cloud', 'abc-123')).toBe('confc:cloud:abc-123');
  });

  it('returns confc:data-center:<id> for data-center instances', () => {
    expect(buildRootScopeExternalId('data-center', '92b23664-16d8-3ab3-9ba5-f3a45b057487')).toBe(
      'confc:data-center:92b23664-16d8-3ab3-9ba5-f3a45b057487',
    );
  });
});

describe('buildSpaceScopeExternalId', () => {
  it('returns confc:<tenantName>:<spaceKey>', () => {
    expect(buildSpaceScopeExternalId('dogfood-cloud', 'ENG')).toBe('confc:dogfood-cloud:ENG');
  });
});
