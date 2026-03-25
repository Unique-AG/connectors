import type { ZodError } from 'zod';

/**
 * Formats a ZodError into a concise string for LLM consumption.
 * Output: "field.path: message; other.field: message"
 */
export function formatZodError(error: ZodError): string {
  return error.issues
    .map((issue) =>
      issue.path.length > 0 ? `${issue.path.join('.')}: ${issue.message}` : issue.message,
    )
    .join('; ');
}
