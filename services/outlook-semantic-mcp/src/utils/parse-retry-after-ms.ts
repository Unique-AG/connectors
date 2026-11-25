/**
 * A `Retry-After` value in milliseconds: delay-seconds, or an HTTP date turned into the time left
 * until it (RFC 9110, section 10.2.3). Null when the value is absent or neither form.
 */
export const parseRetryAfterMs = (
  value: string | null | undefined,
  now: number = Date.now(),
): number | null => {
  const trimmed = value?.trim();
  if (!trimmed) {
    return null;
  }
  if (/^\d+$/.test(trimmed)) {
    return Number(trimmed) * 1000;
  }
  // Every HTTP date names its day or month, so a bare number such as `-5` is not read as a year.
  const date = /[a-z]/i.test(trimmed) ? Date.parse(trimmed) : Number.NaN;
  return Number.isNaN(date) ? null : Math.max(0, date - now);
};
