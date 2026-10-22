import { describe, expect, it } from 'vitest';
import { parseAttachmentUri } from './parse-attachment-uri';

describe('parseAttachmentUri', () => {
  describe('unique:// scheme', () => {
    it('parses a valid unique URI', () => {
      const result = parseAttachmentUri('unique://content/cont_j23i0ifr44sdn7cz97ubleb7');

      expect(result).toEqual({
        type: 'unique',
        contentId: 'cont_j23i0ifr44sdn7cz97ubleb7',
      });
    });

    it('rejects old-style unique URI with chatId in path', () => {
      expect(() => parseAttachmentUri('unique://chat/chat_abc123/content/cont_abc')).toThrow(
        'Unsupported attachment URI scheme',
      );
    });
  });

  describe('data: scheme', () => {
    it('parses a base64 data URI', () => {
      const base64Content = Buffer.from('hello world').toString('base64');
      const result = parseAttachmentUri(`data:text/plain;base64,${base64Content}`);

      expect(result).toEqual({
        type: 'data',
        mimeType: 'text/plain',
        data: Buffer.from('hello world'),
      });
    });

    it('parses a URL-encoded data URI', () => {
      const result = parseAttachmentUri('data:text/plain,Hello%20World');

      expect(result).toEqual({
        type: 'data',
        mimeType: 'text/plain',
        data: Buffer.from('Hello World'),
      });
    });

    it('defaults mime type to application/octet-stream', () => {
      const base64Content = Buffer.from('binary data').toString('base64');
      const result = parseAttachmentUri(`data:;base64,${base64Content}`);

      expect(result).toEqual({
        type: 'data',
        mimeType: 'application/octet-stream',
        data: Buffer.from('binary data'),
      });
    });

    it('parses application/pdf mime type', () => {
      const base64Content = Buffer.from('%PDF-1.4').toString('base64');
      const result = parseAttachmentUri(`data:application/pdf;base64,${base64Content}`);

      expect(result.type).toBe('data');
      if (result.type === 'data') {
        expect(result.mimeType).toBe('application/pdf');
      }
    });

    it('parses base64 that wraps across lines', () => {
      const payload = Buffer.from('hello world');
      const wrapped = payload.toString('base64').replace(/(.{4})/g, '$1\n');
      const result = parseAttachmentUri(`data:text/plain;base64,${wrapped}`);

      expect(result).toEqual({
        type: 'data',
        mimeType: 'text/plain',
        data: payload,
      });
    });

    it('parses base64 with the padding characters omitted', () => {
      const payload = Buffer.from('a');
      const unpadded = payload.toString('base64').replace(/=+$/, '');
      const result = parseAttachmentUri(`data:text/plain;base64,${unpadded}`);

      expect(result).toEqual({
        type: 'data',
        mimeType: 'text/plain',
        data: payload,
      });
    });

    it('rejects base64 whose length is one more than a multiple of four', () => {
      expect(() => parseAttachmentUri('data:text/plain;base64,A')).toThrow(
        'Attachment data is truncated and cannot be opened',
      );
    });

    it('parses a complete Word file', () => {
      const zip = buildStoredZip('word/document.xml', Buffer.from('<document/>'));
      const result = parseAttachmentUri(
        `data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,${zip.toString('base64')}`,
      );

      expect(result).toEqual({
        type: 'data',
        mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        data: zip,
      });
    });

    it('rejects a Word file whose zip directory sits past the end of the buffer', () => {
      const truncated = truncateZip(
        buildStoredZip('word/document.xml', Buffer.from('<document/>')),
      );

      expect(() =>
        parseAttachmentUri(
          `data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,${truncated.toString('base64')}`,
        ),
      ).toThrow('Attachment data is truncated and cannot be opened');
    });

    it('rejects a Word file that is not a zip', () => {
      const payload = Buffer.from('not a zip');

      expect(() =>
        parseAttachmentUri(
          `data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,${payload.toString('base64')}`,
        ),
      ).toThrow('Attachment is not a valid Office file and cannot be opened');
    });

    it('parses a complete zip sent as application/octet-stream', () => {
      const zip = buildStoredZip('word/document.xml', Buffer.from('<document/>'));
      const result = parseAttachmentUri(
        `data:application/octet-stream;base64,${zip.toString('base64')}`,
      );

      expect(result).toEqual({
        type: 'data',
        mimeType: 'application/octet-stream',
        data: zip,
      });
    });

    it('rejects a truncated zip sent as application/octet-stream', () => {
      const truncated = truncateZip(
        buildStoredZip('word/document.xml', Buffer.from('<document/>')),
      );

      expect(() =>
        parseAttachmentUri(`data:application/octet-stream;base64,${truncated.toString('base64')}`),
      ).toThrow('Attachment data is truncated and cannot be opened');
    });
  });

  describe('unsupported schemes', () => {
    it('throws for https:// URLs (SSRF risk)', () => {
      expect(() => parseAttachmentUri('https://example.com/file.pdf')).toThrow(
        'Unsupported attachment URI scheme',
      );
    });

    it('throws for http:// URLs (SSRF risk)', () => {
      expect(() => parseAttachmentUri('http://example.com/file.pdf')).toThrow(
        'Unsupported attachment URI scheme',
      );
    });

    it('throws for ftp:// scheme', () => {
      expect(() => parseAttachmentUri('ftp://example.com/file')).toThrow(
        'Unsupported attachment URI scheme',
      );
    });

    it('throws for empty string', () => {
      expect(() => parseAttachmentUri('')).toThrow('Unsupported attachment URI scheme');
    });

    it('throws for plain text', () => {
      expect(() => parseAttachmentUri('just-some-text')).toThrow(
        'Unsupported attachment URI scheme',
      );
    });
  });
});

function truncateZip(zip: Buffer): Buffer {
  const endOfDirectory = zip.subarray(zip.length - 22);
  return Buffer.concat([zip.subarray(0, 8), endOfDirectory]);
}

function buildStoredZip(name: string, content: Buffer): Buffer {
  const fileName = Buffer.from(name);
  const localHeader = Buffer.concat([
    uint32(0x04034b50),
    uint16(20),
    uint16(0),
    uint16(0),
    uint16(0),
    uint16(0),
    uint32(0),
    uint32(content.length),
    uint32(content.length),
    uint16(fileName.length),
    uint16(0),
    fileName,
    content,
  ]);
  const centralDirectory = Buffer.concat([
    uint32(0x02014b50),
    uint16(20),
    uint16(20),
    uint16(0),
    uint16(0),
    uint16(0),
    uint16(0),
    uint32(0),
    uint32(content.length),
    uint32(content.length),
    uint16(fileName.length),
    uint16(0),
    uint16(0),
    uint16(0),
    uint16(0),
    uint32(0),
    uint32(0),
    fileName,
  ]);
  const endOfCentralDirectory = Buffer.concat([
    uint32(0x06054b50),
    uint16(0),
    uint16(0),
    uint16(1),
    uint16(1),
    uint32(centralDirectory.length),
    uint32(localHeader.length),
    uint16(0),
  ]);

  return Buffer.concat([localHeader, centralDirectory, endOfCentralDirectory]);
}

function uint16(value: number): Buffer {
  const buffer = Buffer.alloc(2);
  buffer.writeUInt16LE(value);
  return buffer;
}

function uint32(value: number): Buffer {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32LE(value);
  return buffer;
}
