import { describe, expect, it } from 'vitest';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import { resolveMimeType } from './resolve-mime-type';

describe('resolveMimeType', () => {
  describe('suffix overrides', () => {
    it('resolves a custom suffix to its configured mimeType', () => {
      expect(
        resolveMimeType('quarterly.xls', 'application/octet-stream', {
          '.xls': 'application/vnd.ms-excel',
        }),
      ).toBe('application/vnd.ms-excel');
    });

    it('prefers the override over the raw mimeType', () => {
      expect(
        resolveMimeType('export.csv', 'application/vnd.ms-excel', { '.csv': 'application/csv' }),
      ).toBe('application/csv');
    });

    it('does not match a suffix that appears only as a substring of the file name', () => {
      expect(
        resolveMimeType('notes.csvbackup', 'application/octet-stream', { '.csv': 'text/csv' }),
      ).toBe('application/octet-stream');
    });

    it('returns the override mimeType even when raw mimeType is undefined', () => {
      expect(resolveMimeType('report.csv', undefined, { '.csv': 'text/csv' })).toBe('text/csv');
    });
  });

  describe('case-insensitive matching', () => {
    it('matches an uppercase file extension against a lowercase suffix key', () => {
      expect(resolveMimeType('Foo.CSV', 'text/plain', { '.csv': 'text/csv' })).toBe('text/csv');
    });

    it('matches a lowercase file extension against an uppercase suffix key', () => {
      expect(resolveMimeType('foo.csv', 'text/plain', { '.CSV': 'text/csv' })).toBe('text/csv');
    });

    it('matches a mixed-case file extension against a mixed-case suffix key', () => {
      expect(resolveMimeType('Report.CsV', 'text/plain', { '.cSv': 'text/csv' })).toBe('text/csv');
    });
  });

  describe('multi-segment suffixes', () => {
    it('matches a multi-segment suffix like .tar.gz', () => {
      expect(
        resolveMimeType('archive.tar.gz', 'application/octet-stream', {
          '.tar.gz': 'application/gzip',
        }),
      ).toBe('application/gzip');
    });
  });

  describe('longest match wins', () => {
    it('selects .tar.gz over .gz when both are configured', () => {
      expect(
        resolveMimeType('archive.tar.gz', 'application/octet-stream', {
          '.gz': 'application/x-gzip',
          '.tar.gz': 'application/gzip',
        }),
      ).toBe('application/gzip');
    });

    it('selects the shorter suffix when the longer one does not match', () => {
      expect(
        resolveMimeType('notes.gz', 'application/octet-stream', {
          '.gz': 'application/x-gzip',
          '.tar.gz': 'application/gzip',
        }),
      ).toBe('application/x-gzip');
    });
  });

  describe('fallback behavior', () => {
    it('falls through to raw mimeType for files without an extension', () => {
      expect(resolveMimeType('README', 'text/plain', { '.csv': 'text/csv' })).toBe('text/plain');
    });

    it('falls back to raw mimeType when no override matches', () => {
      expect(resolveMimeType('document.pdf', 'application/pdf', { '.csv': 'text/csv' })).toBe(
        'application/pdf',
      );
    });

    it('falls back to DEFAULT_MIME_TYPE when no override matches and raw mimeType is undefined', () => {
      expect(resolveMimeType('document.pdf', undefined, { '.csv': 'text/csv' })).toBe(
        DEFAULT_MIME_TYPE,
      );
    });

    it('falls back to DEFAULT_MIME_TYPE when overrides are empty and raw mimeType is undefined', () => {
      expect(resolveMimeType('document.pdf', undefined, {})).toBe(DEFAULT_MIME_TYPE);
    });

    it('returns DEFAULT_MIME_TYPE for an empty filename and undefined raw mimeType', () => {
      expect(resolveMimeType('', undefined, { '.csv': 'text/csv' })).toBe(DEFAULT_MIME_TYPE);
    });
  });
});
