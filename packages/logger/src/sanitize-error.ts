import { stdSerializers } from 'pino-http';

interface GraphqlClientErrorLike extends Error {
  response: Record<string, unknown>;
}

interface SanitizedGraphqlError {
  message: string;
  path?: ReadonlyArray<string | number>;
  code?: unknown;
}

interface SanitizedError {
  name?: string;
  message?: string;
  stack?: string;
  graphqlErrors?: SanitizedGraphqlError[];
  statusCode?: number;
  [key: string]: unknown;
}

export function sanitizeError(error: unknown): unknown {
  if (isGraphqlClientError(error)) {
    return sanitizeGraphqlClientError(error);
  }

  return error instanceof Error ? stdSerializers.err(error) : error;
}

function isGraphqlClientError(error: unknown): error is GraphqlClientErrorLike {
  return (
    error instanceof Error &&
    error.name === 'ClientError' &&
    'response' in error &&
    isRecord(error.response)
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
  return path.every((segment) => typeof segment === 'string' || typeof segment === 'number')
    ? path
    : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
