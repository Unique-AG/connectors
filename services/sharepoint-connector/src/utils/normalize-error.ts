import { ClientError } from 'graphql-request';
import { serializeError } from 'serialize-error-cjs';

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
export function sanitizeError(error: unknown): object {
  if (error instanceof ClientError) {
    const jsonDumpStart = error.message.indexOf(': {"response":');
    const baseMessage = jsonDumpStart >= 0 ? error.message.slice(0, jsonDumpStart) : error.message;

    return {
      name: error.name,
      message: baseMessage,
      stack: error.stack?.replace(error.message, baseMessage),
      graphqlErrors: error.response.errors?.map((e) => ({
        message: e.message,
        path: e.path,
        code: e.extensions?.code,
      })),
      statusCode: error.response.status,
    };
  }

  const normalized = normalizeError(error);
  // serializeError reads `name` from the prototype, so it reports `Error` for subclasses that set
  // `this.name` in their constructor.
  const serialized = { ...serializeError(normalized), name: normalized.name };
  if (normalized.cause === undefined) {
    return serialized;
  }
  // serializeError turns `cause` into `{}`, which hides why a wrapping error such as
  // PermissionsSyncError was thrown.
  return { ...serialized, cause: sanitizeError(normalized.cause) };
}
