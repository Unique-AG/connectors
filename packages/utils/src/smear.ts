/**
 * @description
 * Masks a string by replacing alphanumeric characters with asterisks,
 * leaving only the last few characters visible. Used to obfuscate
 * diagnostic data (names, emails, paths) in production logs.
 *
 * Returns `"__erroneous__"` for nullish input, `"[Smeared]"` when the
 * string is too short to meaningfully mask (fewer than 3 characters would
 * be replaced).
 *
 * Smear function should be used to obfuscate logs like emails / names basically details
 * which are not super sensitive but it's still usefull to see a small part of the origninal
 * string for debugging purpuses. For secrets always use Redacted.
 *
 * @param text - The value to mask.
 * @param leaveOver - Number of trailing characters to keep visible (default `4`).
 *
 * @example
 * smear('password');        // "****word"
 * smear('mySecret123');     // "*******t123"
 * smear('hello', 2);        // "***lo"
 * smear('ab');               // "[Smeared]"
 * smear(null);               // "__erroneous__"
 */
export function smear(text: string | null | undefined, leaveOver = 4) {
  if (text === undefined || text === null) {
    return '__erroneous__';
  }
  if (!text.length || text.length <= leaveOver) return '[Smeared]';

  const charsToSmear = text.length - leaveOver;
  if (charsToSmear < 3) return '[Smeared]';

  const end = text.substring(text.length - leaveOver, text.length);
  const toSmear = text.substring(0, text.length - leaveOver);
  return `${toSmear.replaceAll(/[a-zA-Z0-9_]/g, '*')}${end}`;
}
