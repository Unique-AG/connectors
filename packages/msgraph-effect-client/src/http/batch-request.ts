import type { BatchItemError } from '../errors/errors.js';

export interface BatchRequestItem {
  readonly id: string;
  readonly method: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  readonly url: string;
  readonly body?: unknown;
  readonly headers?: Record<string, string>;
}

export interface BatchResponseItem {
  readonly id: string;
  readonly status: number;
  readonly headers?: Record<string, string>;
  readonly body?: unknown;
  readonly error?: BatchItemError;
}
