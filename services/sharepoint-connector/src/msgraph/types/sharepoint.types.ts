export enum ModerationStatus {
  Approved = 0,
  Rejected = 1,
  Pending = 2,
  Draft = 3,
}

export interface GraphApiErrorResponse {
  statusCode?: number;
  code?: string;
  body?: unknown;
  requestId?: string;
  innerError?: unknown;
  response?: {
    status?: number;
    headers?: Headers | Record<string, string>;
  };
}

export function isGraphApiError(error: unknown): error is GraphApiErrorResponse {
  return (
    typeof error === 'object' &&
    error !== null &&
    ('statusCode' in error || 'code' in error || 'body' in error || 'requestId' in error)
  );
}
