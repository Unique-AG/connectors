import { describe, expect, it } from 'vitest';
import { encodeGraphItemIdForUrlPath } from '../encode-graph-item-id-for-url-path';

describe('encodeGraphItemIdForUrlPath', () => {
  it('replaces slashes with hyphens', () => {
    expect(encodeGraphItemIdForUrlPath('abc/def/ghi')).toBe('abc-def-ghi');
  });

  it('leaves IDs without slashes unchanged', () => {
    expect(encodeGraphItemIdForUrlPath('AAMkADc4ZTM3OWQ4')).toBe('AAMkADc4ZTM3OWQ4');
  });
});
