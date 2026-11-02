import { buffer } from 'node:stream/consumers';
import { describe, expect, it } from 'vitest';
import { ZipFile } from 'yazl';
import { parseAttachmentUri } from './parse-attachment-uri';

const WORD_MIME_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const END_OF_CENTRAL_DIRECTORY_SIZE = 22;

describe('parseAttachmentUri', () => {
  describe('unique:// scheme', () => {
    it('parses a valid unique URI', async () => {
      const result = await parseAttachmentUri('unique://content/cont_j23i0ifr44sdn7cz97ubleb7');

      expect(result).toEqual({
        type: 'unique',
        contentId: 'cont_j23i0ifr44sdn7cz97ubleb7',
      });
    });

    it('rejects old-style unique URI with chatId in path', async () => {
      await expect(
        parseAttachmentUri('unique://chat/chat_abc123/content/cont_abc'),
      ).rejects.toThrow('Unsupported attachment URI scheme');
    });
  });

  describe('data: scheme', () => {
    it('parses a base64 data URI', async () => {
      const base64Content = Buffer.from('hello world').toString('base64');
      const result = await parseAttachmentUri(`data:text/plain;base64,${base64Content}`);

      expect(result).toEqual({
        type: 'data',
        mimeType: 'text/plain',
        data: Buffer.from('hello world'),
      });
    });

    it('parses a URL-encoded data URI', async () => {
      const result = await parseAttachmentUri('data:text/plain,Hello%20World');

      expect(result).toEqual({
        type: 'data',
        mimeType: 'text/plain',
        data: Buffer.from('Hello World'),
      });
    });

    it('defaults mime type to application/octet-stream', async () => {
      const base64Content = Buffer.from('binary data').toString('base64');
      const result = await parseAttachmentUri(`data:;base64,${base64Content}`);

      expect(result).toEqual({
        type: 'data',
        mimeType: 'application/octet-stream',
        data: Buffer.from('binary data'),
      });
    });

    it('parses application/pdf mime type', async () => {
      const base64Content = Buffer.from('%PDF-1.4').toString('base64');
      const result = await parseAttachmentUri(`data:application/pdf;base64,${base64Content}`);

      expect(result.type).toBe('data');
      if (result.type === 'data') {
        expect(result.mimeType).toBe('application/pdf');
      }
    });

    it('parses base64 that wraps across lines', async () => {
      const payload = Buffer.from('hello world');
      const wrapped = payload.toString('base64').replace(/(.{4})/g, '$1\n');
      const result = await parseAttachmentUri(`data:text/plain;base64,${wrapped}`);

      expect(result).toEqual({
        type: 'data',
        mimeType: 'text/plain',
        data: payload,
      });
    });

    it('parses base64 with the padding characters omitted', async () => {
      const payload = Buffer.from('a');
      const unpadded = payload.toString('base64').replace(/=+$/, '');
      const result = await parseAttachmentUri(`data:text/plain;base64,${unpadded}`);

      expect(result).toEqual({
        type: 'data',
        mimeType: 'text/plain',
        data: payload,
      });
    });

    it('rejects base64 whose length is one more than a multiple of four', async () => {
      await expect(parseAttachmentUri('data:text/plain;base64,A')).rejects.toThrow(
        'Attachment data is truncated and cannot be opened',
      );
    });

    it('rejects base64 that contains a character outside the alphabet', async () => {
      await expect(parseAttachmentUri('data:text/plain;base64,QQ=@')).rejects.toThrow(
        'Attachment data is truncated and cannot be opened',
      );
    });

    it('parses a complete Word file', async () => {
      const zip = await buildWordFile();
      const result = await parseAttachmentUri(
        `data:${WORD_MIME_TYPE};base64,${zip.toString('base64')}`,
      );

      expect(result).toEqual({
        type: 'data',
        mimeType: WORD_MIME_TYPE,
        data: zip,
      });
    });

    it('rejects a Word file whose zip directory sits past the end of the buffer', async () => {
      const truncated = truncateZip(await buildWordFile());

      await expect(
        parseAttachmentUri(`data:${WORD_MIME_TYPE};base64,${truncated.toString('base64')}`),
      ).rejects.toThrow('Attachment data is truncated and cannot be opened');
    });

    it('rejects a Word file whose end was cut off', async () => {
      const zip = await buildWordFile();
      const cutOff = zip.subarray(0, Math.floor(zip.length / 2));

      await expect(
        parseAttachmentUri(`data:${WORD_MIME_TYPE};base64,${cutOff.toString('base64')}`),
      ).rejects.toThrow('Attachment data is truncated and cannot be opened');
    });

    it('rejects a Word file whose entry content does not match its checksum', async () => {
      const zip = await buildWordFile();
      const corrupted = Buffer.from(zip);
      corrupted.write('<tampered/>', zip.indexOf('<document/>'));

      await expect(
        parseAttachmentUri(`data:${WORD_MIME_TYPE};base64,${corrupted.toString('base64')}`),
      ).rejects.toThrow('Attachment data is truncated and cannot be opened');
    });

    it('rejects a Word file that unpacks to more than the allowed size', async () => {
      const zip = await buildWordFile();

      await expect(
        parseAttachmentUri(`data:${WORD_MIME_TYPE};base64,${zip.toString('base64')}`, {
          maxUncompressedSize: '<document/>'.length - 1,
        }),
      ).rejects.toThrow('Attachment unpacks to more data than allowed and cannot be attached');
    });

    it('rejects a Word file that is not a zip', async () => {
      const payload = Buffer.from('not a zip');

      await expect(
        parseAttachmentUri(`data:${WORD_MIME_TYPE};base64,${payload.toString('base64')}`),
      ).rejects.toThrow('Attachment is not a valid Office file and cannot be opened');
    });

    it('parses a complete zip sent as application/octet-stream', async () => {
      const zip = await buildWordFile();
      const result = await parseAttachmentUri(
        `data:application/octet-stream;base64,${zip.toString('base64')}`,
      );

      expect(result).toEqual({
        type: 'data',
        mimeType: 'application/octet-stream',
        data: zip,
      });
    });

    it('rejects a truncated zip sent as application/octet-stream', async () => {
      const truncated = truncateZip(await buildWordFile());

      await expect(
        parseAttachmentUri(`data:application/octet-stream;base64,${truncated.toString('base64')}`),
      ).rejects.toThrow('Attachment data is truncated and cannot be opened');
    });
  });

  describe('unsupported schemes', () => {
    it('throws for https:// URLs (SSRF risk)', async () => {
      await expect(parseAttachmentUri('https://example.com/file.pdf')).rejects.toThrow(
        'Unsupported attachment URI scheme',
      );
    });

    it('throws for http:// URLs (SSRF risk)', async () => {
      await expect(parseAttachmentUri('http://example.com/file.pdf')).rejects.toThrow(
        'Unsupported attachment URI scheme',
      );
    });

    it('throws for ftp:// scheme', async () => {
      await expect(parseAttachmentUri('ftp://example.com/file')).rejects.toThrow(
        'Unsupported attachment URI scheme',
      );
    });

    it('throws for empty string', async () => {
      await expect(parseAttachmentUri('')).rejects.toThrow('Unsupported attachment URI scheme');
    });

    it('throws for plain text', async () => {
      await expect(parseAttachmentUri('just-some-text')).rejects.toThrow(
        'Unsupported attachment URI scheme',
      );
    });
  });
});

function buildWordFile(): Promise<Buffer> {
  const zip = new ZipFile();
  zip.addBuffer(Buffer.from('<document/>'), 'word/document.xml', { compress: false });
  zip.end();
  return buffer(zip.outputStream);
}

function truncateZip(zip: Buffer): Buffer {
  const endOfCentralDirectory = zip.subarray(zip.length - END_OF_CENTRAL_DIRECTORY_SIZE);
  return Buffer.concat([zip.subarray(0, 8), endOfCentralDirectory]);
}
