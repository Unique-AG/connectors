export interface BatchRequest {
  id: string;
  method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  url: string;
  headers?: Record<string, string>;
  body?: unknown;
}

export interface BatchResponse<T = unknown> {
  id: string;
  status: number;
  headers?: Record<string, string>;
  body?: T;
}

export interface BatchRequestPayload {
  requests: BatchRequest[];
}

export interface BatchResponsePayload {
  responses: BatchResponse[];
}

export interface BatchResult<T = unknown> {
  success: boolean;
  status: number;
  data?: T;
  error?: BatchError;
}

export interface BatchError {
  code: string;
  message: string;
  innerError?: {
    date: string;
    'request-id': string;
    'client-request-id': string;
  };
}

export interface DriveItemsResponse {
  value: unknown[];
  '@odata.nextLink'?: string;
}

