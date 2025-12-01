import { describe, expect, it } from 'vitest';
import {
  createApiMethodExtractor,
  getHttpStatusCodeClass,
  getSlowRequestDurationBucket,
} from './utils';

describe('getDurationBucket', () => {
  it('returns null for durations under or equal to 1 second', () => {
    expect(getSlowRequestDurationBucket(0)).toBeNull();
    expect(getSlowRequestDurationBucket(500)).toBeNull();
    expect(getSlowRequestDurationBucket(1_000)).toBeNull();
  });

  it('returns >1s for durations between 1 and 2 seconds', () => {
    expect(getSlowRequestDurationBucket(1_001)).toBe('>1s');
    expect(getSlowRequestDurationBucket(1_500)).toBe('>1s');
    expect(getSlowRequestDurationBucket(2_000)).toBe('>1s');
  });

  it('returns >3s for durations between 2 and 5 seconds', () => {
    expect(getSlowRequestDurationBucket(2_001)).toBe('>2s');
    expect(getSlowRequestDurationBucket(3_000)).toBe('>2s');
    expect(getSlowRequestDurationBucket(4_000)).toBe('>2s');
    expect(getSlowRequestDurationBucket(5_000)).toBe('>2s');
  });

  it('returns >5s for durations between 5 and 10 seconds', () => {
    expect(getSlowRequestDurationBucket(5_001)).toBe('>5s');
    expect(getSlowRequestDurationBucket(7_500)).toBe('>5s');
    expect(getSlowRequestDurationBucket(10_000)).toBe('>5s');
  });

  it('returns >10s for durations over 10 seconds', () => {
    expect(getSlowRequestDurationBucket(10_001)).toBe('>10s');
    expect(getSlowRequestDurationBucket(15_000)).toBe('>10s');
    expect(getSlowRequestDurationBucket(100_000)).toBe('>10s');
  });
});

describe('getHttpStatusCodeClass', () => {
  it('returns 2xx for success status codes', () => {
    expect(getHttpStatusCodeClass(200)).toBe('2xx');
    expect(getHttpStatusCodeClass(201)).toBe('2xx');
    expect(getHttpStatusCodeClass(204)).toBe('2xx');
    expect(getHttpStatusCodeClass(299)).toBe('2xx');
  });

  it('returns 3xx for redirection status codes', () => {
    expect(getHttpStatusCodeClass(300)).toBe('3xx');
    expect(getHttpStatusCodeClass(301)).toBe('3xx');
    expect(getHttpStatusCodeClass(302)).toBe('3xx');
    expect(getHttpStatusCodeClass(399)).toBe('3xx');
  });

  it('returns specific code for client error status codes', () => {
    expect(getHttpStatusCodeClass(400)).toBe('400');
    expect(getHttpStatusCodeClass(401)).toBe('401');
    expect(getHttpStatusCodeClass(403)).toBe('403');
    expect(getHttpStatusCodeClass(404)).toBe('404');
    expect(getHttpStatusCodeClass(499)).toBe('499');
  });

  it('returns 5xx for server error status codes', () => {
    expect(getHttpStatusCodeClass(500)).toBe('5xx');
    expect(getHttpStatusCodeClass(502)).toBe('5xx');
    expect(getHttpStatusCodeClass(503)).toBe('5xx');
    expect(getHttpStatusCodeClass(599)).toBe('5xx');
  });

  it('returns unknown for unrecognized status codes', () => {
    expect(getHttpStatusCodeClass(0)).toBe('unknown');
    expect(getHttpStatusCodeClass(100)).toBe('unknown');
    expect(getHttpStatusCodeClass(199)).toBe('unknown');
  });
});

describe('createApiMethodExtractor', () => {
  it('creates extractor for Graph API endpoints', () => {
    const extractor = createApiMethodExtractor(['sites', 'drives', 'items', 'children', 'content']);

    expect(extractor('/sites/abc123/drives', 'GET')).toBe('GET:/sites/{siteId}/drives');
    expect(extractor('/drives/xyz456/items/file789/content', 'GET')).toBe(
      'GET:/drives/{driveId}/items/{itemId}/content',
    );
    expect(extractor('/sites/abc/drives/def/items/ghi/children', 'POST')).toBe(
      'POST:/sites/{siteId}/drives/{driveId}/items/{itemId}/children',
    );
  });

  it('creates extractor for Unique API endpoints', () => {
    const extractor = createApiMethodExtractor(['v2', 'content', 'file-diff', 'scoped']);

    expect(extractor('/v2/content/abc123', 'POST')).toBe('POST:/v2/content/{contentId}');
    expect(extractor('/v2/file-diff/xyz456/scoped', 'GET')).toBe(
      'GET:/v2/file-diff/{file-diffId}/scoped',
    );
  });

  it('handles unknown segments', () => {
    const extractor = createApiMethodExtractor(['known']);

    expect(extractor('/unknown/segment', 'GET')).toBe('GET:/[unknown]/{unknownId}');
  });

  it('handles paths starting with unknown segments', () => {
    const extractor = createApiMethodExtractor(['items']);

    expect(extractor('/random/items/abc', 'DELETE')).toBe('DELETE:/[unknown]/items/{itemId}');
  });

  it('removes trailing s from previous segment for ID naming', () => {
    const extractor = createApiMethodExtractor(['sites', 'drives']);

    expect(extractor('/sites/abc123/drives/def456', 'GET')).toBe(
      'GET:/sites/{siteId}/drives/{driveId}',
    );
  });

  it('handles empty paths', () => {
    const extractor = createApiMethodExtractor(['test']);

    expect(extractor('/', 'GET')).toBe('GET:/');
    expect(extractor('', 'POST')).toBe('POST:/');
  });

  it('handles paths with multiple slashes', () => {
    const extractor = createApiMethodExtractor(['sites']);

    expect(extractor('//sites///abc123//', 'GET')).toBe('GET:/sites/{siteId}');
  });

  it('preserves HTTP method in uppercase', () => {
    const extractor = createApiMethodExtractor(['test']);

    expect(extractor('/test/123', 'get')).toBe('get:/test/{testId}');
    expect(extractor('/test/123', 'POST')).toBe('POST:/test/{testId}');
  });
});
