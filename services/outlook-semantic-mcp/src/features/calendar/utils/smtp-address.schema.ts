import * as z from 'zod';

/**
 * Validates a mailbox address. This is a path-safety boundary, not just input hygiene: these
 * values are interpolated straight into Graph URLs (`/users/${mailbox}/calendars/...`), and some
 * of them arrive from tool input rather than the database. z.email() rejects the URL-structural
 * characters that would let a value escape its path segment, so do not relax it to a plain
 * z.string() — the asserts in calendar-graph-path.ts depend on it.
 */
export const SmtpAddressSchema = z.email('Must be an SMTP address');

export function smtpAddress(description: string) {
  return SmtpAddressSchema.describe(description);
}

/**
 * Deduplicates a caller-supplied address list, preserving order and dropping anything that is not
 * an SMTP address. Graph rejects the whole request on one bad entry, so filtering beats failing.
 */
export function uniqueSmtpAddresses(addresses: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const address of addresses) {
    const trimmed = address.trim();
    const key = trimmed.toLowerCase();
    if (!SmtpAddressSchema.safeParse(trimmed).success || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(trimmed);
  }
  return result;
}
