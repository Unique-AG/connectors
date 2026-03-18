export type ParsedUri =
  | { type: 'unique'; chatId: string; contentId: string }
  | { type: 'data'; mimeType: string; data: Buffer; filename: string }
  | { type: 'url'; url: string };

const UNIQUE_URI_PATTERN = /^unique:\/\/chat\/([^/]*)\/content\/([^/]+)$/;
const DATA_URI_PATTERN = /^data:([^;,]*)(;base64)?,(.*)$/s;

export function parseAttachmentUri(uri: string): ParsedUri {
  const uniqueMatch = uri.match(UNIQUE_URI_PATTERN);
  if (uniqueMatch) {
    const chatId = uniqueMatch[1];
    const contentId = uniqueMatch[2];
    if (chatId && contentId) {
      return { type: 'unique', chatId, contentId };
    }
  }

  const dataMatch = uri.match(DATA_URI_PATTERN);
  const rawData = dataMatch?.[3];
  if (dataMatch && rawData) {
    const mimeType = dataMatch[1] || 'application/octet-stream';
    const isBase64 = dataMatch[2] === ';base64';
    const data = isBase64
      ? Buffer.from(rawData, 'base64')
      : Buffer.from(decodeURIComponent(rawData));

    const ext = mimeType.split('/')[1]?.split('+')[0] ?? 'bin';
    const filename = `attachment.${ext}`;

    return { type: 'data', mimeType, data, filename };
  }

  if (uri.startsWith('https://') || uri.startsWith('http://')) {
    return { type: 'url', url: uri };
  }

  throw new Error(`Unsupported attachment URI scheme: ${uri.slice(0, 30)}`);
}
