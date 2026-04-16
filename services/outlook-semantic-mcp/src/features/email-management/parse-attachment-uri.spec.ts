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
