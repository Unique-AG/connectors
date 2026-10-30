/**
 * Thrown by a tool implementation to surface a user-facing message through the
 * MCP isError tool result. The message is passed to the client as-is.
 *
 * Use this for errors that are safe to show end-users (e.g. invalid input that
 * passed schema validation, resource not found, quota exceeded). For unexpected
 * internal failures, let the exception propagate as a plain Error — the handler
 * will replace it with a generic message and log the original.
 */
export class ToolError extends Error {
  public constructor(message: string) {
    super(message);
    this.name = 'ToolError';
  }
}
