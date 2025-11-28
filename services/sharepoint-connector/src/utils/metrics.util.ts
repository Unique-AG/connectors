export const REQUEST_DURATION_BUCKET_BOUNDARIES = [0.1, 0.5, 1, 2, 5, 10, 20];

export function getDurationBucket(durationMs: number): string | null {
  if (durationMs > 10_000) {
    return '>10s';
  }
  if (durationMs > 5_000) {
    return '>5s';
  }
  if (durationMs > 3_000) {
    return '>3s';
  }
  if (durationMs > 1_000) {
    return '>1s';
  }
  return null;
}

export function getHttpStatusCodeClass(statusCode: number): string {
  if (statusCode >= 200 && statusCode < 300) {
    return '2xx';
  }
  if (statusCode >= 300 && statusCode < 400) {
    return '3xx';
  }
  // We treat 4xx status code differently and report them as-is, because these errors are very
  // specific and it's important to know the exact code to understand what is actually happening.
  if (statusCode >= 400 && statusCode < 500) {
    return statusCode.toString();
  }
  if (statusCode >= 500) {
    return '5xx';
  }
  return 'unknown';
}

export function createApiMethodExtractor(knownSegments: string[]) {
  const knownSegmentsSet = new Set(knownSegments);

  return (path: string, httpMethod: string): string => {
    const segments = path.split('/').filter(Boolean);
    const normalizedSegments: string[] = [];
    let previousSegment = '';

    for (const segment of segments) {
      if (knownSegmentsSet.has(segment)) {
        normalizedSegments.push(segment);
        previousSegment = segment;
      } else {
        const paramName = previousSegment
          ? `{${previousSegment.replace(/s$/, '')}Id}`
          : '[unknown]';
        normalizedSegments.push(paramName);
        previousSegment = segment;
      }
    }

    const normalizedPath = normalizedSegments.join('/');
    return `${httpMethod}:/${normalizedPath}`;
  };
}
