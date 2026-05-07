import { ClientError } from 'graphql-request';

// Matches parenthetical content that embeds customer data (filenames, folder names, job IDs).
// Preserves the plural "(s)" suffix pattern used in error messages like "file(s)".
const BULK_MOVE_SENSITIVE_PAREN_PATTERN = / ?\((?!s\))[^)]*\)/g;

export function toSafeBulkMoveError(error: unknown): Error {
  if (error instanceof ClientError) {
    const serverMessage = error.response.errors?.[0]?.message;
    if (!serverMessage) {
      return new Error(`bulkMove failed with status ${error.response.status}`);
    }
    return new Error(serverMessage.replace(BULK_MOVE_SENSITIVE_PAREN_PATTERN, ''));
  }
  return error instanceof Error ? error : new Error(String(error));
}
