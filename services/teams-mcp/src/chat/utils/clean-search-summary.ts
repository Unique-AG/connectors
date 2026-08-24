import he from 'he';
import striptags from 'striptags';

/**
 * Cleans a Microsoft Search hit summary into plain text.
 *
 * Graph wraps every matched term in the snippet in a numbered hit-highlighting
 * element (`<c0>term</c0>`) and HTML-escapes the surrounding text. The markup is
 * not part of the message, is not documented, and confuses a reader that expects
 * message text, so tags are stripped and entities decoded — the same treatment
 * `normalizeContent` gives a message body, using the same libraries.
 *
 * Returns null for an absent or blank summary so the row reports "no snippet"
 * rather than an empty string.
 */
export function cleanSearchSummary(summary: string | null | undefined): string | null {
  if (!summary) {
    return null;
  }

  const text = he
    .decode(striptags(summary))
    .replace(/[^\S\n]+/g, ' ')
    .trim();

  return text || null;
}
