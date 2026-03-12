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
 * - Adaptive card JSON blobs  →  [card]
 * - All other tags stripped, text kept
 * - &amp; &lt; &gt; &nbsp; &quot; &#39; decoded
 *
 * Returns '[deleted]' for blank/tombstone content.
 * Returns content unchanged when contentType is 'text'.
 */
export function normalizeContent(
  content: string,
  contentType: string,
  attachments: Attachment[] = [],
): string {
  if (contentType !== 'html') return content.trim() || '[deleted]';

  const attachmentMap = new Map(attachments.map((a) => [a.id, a.name]));

  let result = content;

  // Block-level elements → newlines
  result = result.replace(/<\/p>/gi, '\n');
  result = result.replace(/<br\s*\/?>/gi, '\n');
  result = result.replace(/<\/li>/gi, '\n');
  result = result.replace(/<li[^>]*>/gi, '- ');

  // Mentions: <at id="0">Alice</at> → @Alice
  result = result.replace(/<at[^>]*>(.*?)<\/at>/gi, '@$1');

  // Attachments: <attachment id="uuid"/> → [attachment: name] or [attachment]
  result = result.replace(/<attachment[^>]*\bid="([^"]+)"[^>]*\/?>/gi, (_, id) => {
    const name = attachmentMap.get(id);
    return name ? `[attachment: ${name}]` : '[attachment]';
  });

  // Strip remaining HTML tags (formatting like <strong>, <em>, etc. — text kept)
  result = result.replace(/<[^>]+>/g, '');

  // Decode common HTML entities
  result = result
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");

  // Collapse excess blank lines
  result = result.replace(/\n{3,}/g, '\n\n').trim();

  // Detect adaptive card / raw JSON blobs
  if (result.startsWith('{') && result.includes('"type"')) {
    return '[card]';
  }

  return result || '[deleted]';
}
