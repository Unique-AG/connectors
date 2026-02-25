import { isObjectType } from 'remeda';

export function getSlowRequestDurationBucket(durationMs: number): string | null {
  if (durationMs > 10_000) return '>10s';
  if (durationMs > 5_000) return '>5s';
  if (durationMs > 2_000) return '>2s';
  if (durationMs > 1_000) return '>1s';
  return null;
}

export function getHttpStatusCodeClass(statusCode: number): string {
  if (statusCode >= 200 && statusCode < 300) return '2xx';
  if (statusCode >= 300 && statusCode < 400) return '3xx';
  // 4xx codes are reported as-is because the specific code matters for debugging
  if (statusCode >= 400 && statusCode < 500) return statusCode.toString();
  if (statusCode >= 500) return '5xx';
  return 'unknown';
}

export function getErrorCodeFromGraphqlRequest(error: unknown): number {
  if (!isObjectType(error)) {
    return 0;
  }

  const graphQlError = error as {
    response?: {
      errors?: Array<{
        extensions?: {
          response?: {
            statusCode?: number;
          };
        };
      }>;
    };
  };

  return graphQlError?.response?.errors?.[0]?.extensions?.response?.statusCode ?? 0;
}

export function createApiMethodExtractor(knownSegments: string[]) {
  const knownSegmentsSet = new Set(knownSegments);

  return (path: string, httpMethod: string): string => {
    const [pathWithoutQueryString] = path.split('?');
    const segments = pathWithoutQueryString?.split('/').filter(Boolean) ?? [];
    const normalizedSegments: string[] = [];
    let previousSegment: string | null = null;

    for (const segment of segments) {
      if (knownSegmentsSet.has(segment)) {
        normalizedSegments.push(segment);
        previousSegment = segment;
      } else {
        const paramName = previousSegment
          ? `{${previousSegment.replace(/s$/, '')}Id}`
          : '[unknown]';
        normalizedSegments.push(paramName);
        previousSegment = null;
      }
    }

    const normalizedPath = normalizedSegments.join('/');
    return `${httpMethod}:/${normalizedPath}`;
  };
}
