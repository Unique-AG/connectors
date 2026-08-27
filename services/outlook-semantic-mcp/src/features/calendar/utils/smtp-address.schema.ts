import * as z from 'zod';

/**
 * Validates an attendee address. These arrive from tool input and go into Graph request bodies —
 * attendee lists, `schedules` on getSchedule, `findMeetingTimes`. Graph rejects an entire request
 * on one malformed entry, so screening here is what keeps one bad address from failing the call.
 */
export const SmtpAddressSchema = z.email('Must be an SMTP address');

export function smtpAddress(description: string) {
  return SmtpAddressSchema.describe(description);
}

/** Deduplicates a caller-supplied address list, preserving order and dropping non-addresses. */
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
