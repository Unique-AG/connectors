import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import { MimeTypeResolverService } from './mime-type-resolver.service';

const buildService = async (overrides: Record<string, string>) => {
  const { unit } = await TestBed.solitary(MimeTypeResolverService)
    .mock(ConfigService)
    .impl((stub) => ({
      ...stub(),
      get: vi.fn((key: string) => {
        if (key === 'processing.mimeTypeOverridesByExtension') {
          return overrides;
        }
        return undefined;
      }),
    }))
    .compile();
  return unit;
};

describe('MimeTypeResolverService', () => {
  describe('suffix overrides', () => {
    it('resolves a custom suffix to its configured mimeType', async () => {
      const service = await buildService({ '.xls': 'application/vnd.ms-excel' });
      expect(service.resolve('quarterly.xls', 'application/octet-stream')).toBe(
        'application/vnd.ms-excel',
      );
    });

    it('prefers the override over the raw mimeType', async () => {
      const service = await buildService({ '.csv': 'application/csv' });
      expect(service.resolve('export.csv', 'application/vnd.ms-excel')).toBe('application/csv');
    });

    it('does not match a suffix that appears only as a substring of the file name', async () => {
      const service = await buildService({ '.csv': 'text/csv' });
      expect(service.resolve('notes.csvbackup', 'application/octet-stream')).toBe(
        'application/octet-stream',
      );
    });

    it('returns the override mimeType even when raw mimeType is undefined', async () => {
      const service = await buildService({ '.csv': 'text/csv' });
      expect(service.resolve('report.csv', undefined)).toBe('text/csv');
    });
  });

  describe('case-insensitive matching', () => {
    it('matches an uppercase file extension against a lowercase suffix key', async () => {
      const service = await buildService({ '.csv': 'text/csv' });
      expect(service.resolve('Foo.CSV', 'text/plain')).toBe('text/csv');
    });

    it('matches a lowercase file extension against an uppercase suffix key', async () => {
      const service = await buildService({ '.CSV': 'text/csv' });
      expect(service.resolve('foo.csv', 'text/plain')).toBe('text/csv');
    });

    it('matches a mixed-case file extension against a mixed-case suffix key', async () => {
      const service = await buildService({ '.cSv': 'text/csv' });
      expect(service.resolve('Report.CsV', 'text/plain')).toBe('text/csv');
    });
  });

  describe('multi-segment suffixes', () => {
    it('matches a multi-segment suffix like .tar.gz', async () => {
      const service = await buildService({ '.tar.gz': 'application/gzip' });
      expect(service.resolve('archive.tar.gz', 'application/octet-stream')).toBe(
        'application/gzip',
      );
    });
  });

  describe('longest match wins', () => {
    it('selects .tar.gz over .gz when both are configured', async () => {
      const service = await buildService({
        '.gz': 'application/x-gzip',
        '.tar.gz': 'application/gzip',
      });
      expect(service.resolve('archive.tar.gz', 'application/octet-stream')).toBe(
        'application/gzip',
      );
    });

    it('selects the shorter suffix when the longer one does not match', async () => {
      const service = await buildService({
        '.gz': 'application/x-gzip',
        '.tar.gz': 'application/gzip',
      });
      expect(service.resolve('notes.gz', 'application/octet-stream')).toBe('application/x-gzip');
    });
  });

  describe('fallback behavior', () => {
    it('falls through to raw mimeType for files without an extension', async () => {
      const service = await buildService({ '.csv': 'text/csv' });
      expect(service.resolve('README', 'text/plain')).toBe('text/plain');
    });

    it('falls back to raw mimeType when no override matches', async () => {
      const service = await buildService({ '.csv': 'text/csv' });
      expect(service.resolve('document.pdf', 'application/pdf')).toBe('application/pdf');
    });

    it('falls back to DEFAULT_MIME_TYPE when no override matches and raw mimeType is undefined', async () => {
      const service = await buildService({ '.csv': 'text/csv' });
      expect(service.resolve('document.pdf', undefined)).toBe(DEFAULT_MIME_TYPE);
    });

    it('falls back to DEFAULT_MIME_TYPE when overrides are empty and raw mimeType is undefined', async () => {
      const service = await buildService({});
      expect(service.resolve('document.pdf', undefined)).toBe(DEFAULT_MIME_TYPE);
    });

    it('returns DEFAULT_MIME_TYPE for an empty filename and undefined raw mimeType', async () => {
      const service = await buildService({ '.csv': 'text/csv' });
      expect(service.resolve('', undefined)).toBe(DEFAULT_MIME_TYPE);
    });
  });
});
