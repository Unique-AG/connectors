import he from 'he';
import striptags from 'striptags';

interface Attachment {
  id: string;
  name: string | null;
}

/**
 * Converts Teams HTML message content to readable plain text.
 *
 * Transforms:
 * - <at>Name</at>  →  @Name
 * - </p>, <br>     →  newline
 * - <li>           →  "- " prefix
 * - <attachment id="x"/>  →  [attachment: name] (or [attachment] if name unknown)
 * - <img …>        →  [image] (inline/hosted-content images carry no text)
 * - Adaptive card JSON blobs  →  [card]
 * - All other tags stripped via `striptags`
 * - HTML entities decoded via `he`
 *
 * Returns '[deleted]' only when `deletedDateTime` is set (Graph's tombstone
 * signal) — never as a fallback for otherwise-empty content, which is more
 * often an image, sticker, or card. Content-light messages fall back to
 * '[no text content]'. Returns content unchanged when contentType is 'text'.
 */
export function normalizeContent(
  content: string,
  contentType: string,
  attachments: Attachment[] = [],
  deletedDateTime?: string | null,
): string {
  if (deletedDateTime) {
    return '[deleted]';
  }

  if (contentType !== 'html') {
    return content.trim() || '[no text content]';
  }

  const attachmentMap = new Map(attachments.map((a) => [a.id, a.name]));

  let result = content;

  // Block-level elements → newlines
  result = result.replace(/<\/p>/gi, '\n');
  result = result.replace(/<br\s*\/?>/gi, '\n');
  result = result.replace(/<\/li>/gi, '\n');
  result = result.replace(/<li[^>]*>/gi, '- ');

  // Mentions: <at id="0">Alice</at> → @Alice (inner text sanitized before substitution)
  result = result.replace(/<at[^>]*>(.*?)<\/at>/gi, (_, name: string) => `@${striptags(name)}`);

  // Attachments: <attachment id="uuid"/> → [attachment: name] or [attachment]
  result = result.replace(/<attachment[^>]*\bid="([^"]+)"[^>]*\/?>/gi, (_, id) => {
    const name = attachmentMap.get(id);
    return name ? `[attachment: ${name}]` : '[attachment]';
  });

  // Inline / hosted-content images: <img …> → [image]. These are not <attachment>
  // elements, so without this rule striptags would drop them to an empty string.
  result = result.replace(/<img[^>]*>/gi, '[image]');

  // Strip remaining HTML tags (formatting like <strong>, <em>, etc. — text kept)
  result = striptags(result);

  // Decode HTML entities
  result = he.decode(result);

  // Collapse excess blank lines
  result = result.replace(/\n{3,}/g, '\n\n').trim();

  // Detect adaptive card / raw JSON blobs
  if (result.startsWith('{') && result.includes('"type"')) {
    return '[card]';
  }

  return result || '[no text content]';
}
