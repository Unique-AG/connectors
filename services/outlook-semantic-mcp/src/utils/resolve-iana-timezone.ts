import { findIana } from 'windows-iana';

/**
 * Returns an IANA timezone identifier for the given string.
 * Accepts both IANA names (passed through unchanged) and Windows timezone IDs
 * (e.g. "Eastern Standard Time") as returned by Microsoft Graph /me/mailboxSettings.
 * Returns undefined for unrecognised values.
 */
export function resolveIanaTimezone(timezone: string): string | undefined {
  const ianaMatches = findIana(timezone);
  if (ianaMatches.length > 0) {
    return ianaMatches[0];
  }
  try {
    Intl.DateTimeFormat(undefined, { timeZone: timezone });
    return timezone;
  } catch {
    return undefined;
  }
}
