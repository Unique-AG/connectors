import { serializeError } from 'serialize-error-cjs';

export function normalizeError(error: unknown): Error {
  if (error instanceof Error) return error;

  if (typeof error === 'string') return new Error(error);

  if (error === null) return new Error('null');
  if (error === undefined) return new Error('undefined');

  if (typeof error === 'symbol') return new Error(error.toString());
  if (typeof error === 'function') return new Error(error.toString());

  try {
    return new Error(JSON.stringify(error));
  } catch {
    // Handle circular references or non-serializable objects
    return new Error(String(error));
  }
}

export function sanitizeError(error: unknown): object {
  return serializeError(normalizeError(error));
}
