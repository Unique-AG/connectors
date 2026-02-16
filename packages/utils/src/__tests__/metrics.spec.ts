import { describe, expect, it } from 'vitest';
import {
  createApiMethodExtractor,
  getErrorCodeFromGraphqlRequest,
  getHttpStatusCodeClass,
  getSlowRequestDurationBucket,
} from '../metrics';

describe('getSlowRequestDurationBucket', () => {
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

  it('returns >2s for durations between 2 and 5 seconds', () => {
    expect(getSlowRequestDurationBucket(2_001)).toBe('>2s');
    expect(getSlowRequestDurationBucket(3_000)).toBe('>2s');
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

describe('getErrorCodeFromGraphqlRequest', () => {
  it('returns 0 for non-object errors', () => {
    expect(getErrorCodeFromGraphqlRequest(null)).toBe(0);
    expect(getErrorCodeFromGraphqlRequest(undefined)).toBe(0);
    expect(getErrorCodeFromGraphqlRequest('string error')).toBe(0);
    expect(getErrorCodeFromGraphqlRequest(42)).toBe(0);
  });

  it('returns 0 when error has no response', () => {
    expect(getErrorCodeFromGraphqlRequest({})).toBe(0);
    expect(getErrorCodeFromGraphqlRequest({ response: {} })).toBe(0);
  });

  it('returns status code from graphql error extensions', () => {
    const error = {
      response: {
        errors: [{ extensions: { response: { statusCode: 404 } } }],
      },
    };
    expect(getErrorCodeFromGraphqlRequest(error)).toBe(404);
  });

  it('returns status code from first error only', () => {
    const error = {
      response: {
        errors: [
          { extensions: { response: { statusCode: 400 } } },
          { extensions: { response: { statusCode: 500 } } },
        ],
      },
    };
    expect(getErrorCodeFromGraphqlRequest(error)).toBe(400);
  });
});

describe('createApiMethodExtractor', () => {
  it('normalizes known segments and parameterizes IDs', () => {
    const extractor = createApiMethodExtractor(['sites', 'drives', 'items', 'children', 'content']);

    expect(extractor('/sites/abc123/drives', 'GET')).toBe('GET:/sites/{siteId}/drives');
    expect(extractor('/drives/xyz456/items/file789/content', 'GET')).toBe(
      'GET:/drives/{driveId}/items/{itemId}/content',
    );
  });

  it('handles unknown segments', () => {
    const extractor = createApiMethodExtractor(['known']);
    expect(extractor('/unknown/segment', 'GET')).toBe('GET:/[unknown]/[unknown]');
  });

  it('handles paths with query strings', () => {
    const extractor = createApiMethodExtractor(['sites', 'drives']);
    expect(extractor('/sites/abc123/drives?filter=xyz', 'GET')).toBe('GET:/sites/{siteId}/drives');
  });

  it('handles empty paths', () => {
    const extractor = createApiMethodExtractor(['test']);
    expect(extractor('/', 'GET')).toBe('GET:/');
    expect(extractor('', 'POST')).toBe('POST:/');
  });
});
