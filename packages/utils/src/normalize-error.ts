import { serializeError } from 'serialize-error-cjs';

interface GraphqlClientErrorLike extends Error {
  response: Record<string, unknown>;
  request: Record<string, unknown>;
}

export interface SanitizedGraphqlError {
  message: string;
  path?: ReadonlyArray<string | number>;
  code?: unknown;
}

export interface SanitizedError {
  name?: string;
  message?: string;
  stack?: string;
  graphqlErrors?: SanitizedGraphqlError[];
  statusCode?: number;
  [key: string]: unknown;
}

export function normalizeError(error: unknown): Error {
  if (error instanceof Error) {
    return error;
  }

  if (typeof error === 'string') {
    return new Error(error);
  }

  if (error === null) {
    return new Error('null');
  }
  if (error === undefined) {
    return new Error('undefined');
  }

  if (typeof error === 'symbol') {
    return new Error(error.toString());
  }
  if (typeof error === 'function') {
    return new Error(error.toString());
  }

  try {
    return new Error(JSON.stringify(error));
  } catch {
    // Handle circular references or non-serializable objects
    return new Error(String(error));
  }
}

/**
 * Serialises an error for structured logging.
 *
 * For `graphql-request` `ClientError` instances the full request payload
 * (query + raw variables) that the library embeds in `message` / `stack` is
 * stripped and replaced with structured `graphqlErrors` and `statusCode`
 * fields, so unsanitised variables never reach the logs.
 */
export function sanitizeError(error: unknown): SanitizedError {
  if (isGraphqlClientError(error)) {
    return sanitizeGraphqlClientError(error);
  }

  return serializeError(normalizeError(error));
}

function isGraphqlClientError(error: unknown): error is GraphqlClientErrorLike {
  return (
    error instanceof Error &&
    'response' in error &&
    isRecord(error.response) &&
    'request' in error &&
    isRecord(error.request) &&
    error.message.includes(': {"response":')
  );
}

function sanitizeGraphqlClientError(error: GraphqlClientErrorLike): SanitizedError {
  const jsonDumpStart = error.message.indexOf(': {"response":');
  const baseMessage = jsonDumpStart >= 0 ? error.message.slice(0, jsonDumpStart) : error.message;
  const graphqlErrors = sanitizeGraphqlErrors(error.response.errors);
  const statusCode = error.response.status;

  return {
    name: error.name,
    message: baseMessage,
    ...(error.stack ? { stack: error.stack.replace(error.message, () => baseMessage) } : {}),
    ...(graphqlErrors ? { graphqlErrors } : {}),
    ...(typeof statusCode === 'number' ? { statusCode } : {}),
  };
}

function sanitizeGraphqlErrors(errors: unknown): SanitizedGraphqlError[] | undefined {
  if (!Array.isArray(errors)) {
    return undefined;
  }

  const sanitizedErrors = errors.flatMap((error): SanitizedGraphqlError[] => {
    if (!isRecord(error) || typeof error.message !== 'string') {
      return [];
    }

    const path = Array.isArray(error.path) ? sanitizeGraphqlPath(error.path) : undefined;
    const extensions = isRecord(error.extensions) ? error.extensions : undefined;

    return [
      {
        message: error.message,
        ...(path ? { path } : {}),
        ...(extensions && 'code' in extensions ? { code: extensions.code } : {}),
      },
    ];
  });

  return sanitizedErrors.length > 0 ? sanitizedErrors : undefined;
}

function sanitizeGraphqlPath(path: unknown[]): ReadonlyArray<string | number> | undefined {
  return path.every(isGraphqlPathSegment) ? path : undefined;
}

function isGraphqlPathSegment(segment: unknown): segment is string | number {
  return typeof segment === 'string' || typeof segment === 'number';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
