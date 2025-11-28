import { describe, expect, it } from 'vitest';
import {
  concealIngestionKey,
  redact,
  redactSiteNameFromPath,
  shouldConcealLogs,
  smear,
  smearSiteIdFromPath,
} from './logging.util';

describe('logging utilities', () => {
  describe('redact', () => {
    it('returns __erroneous__ for null input', () => {
      expect(redact(null)).toBe('__erroneous__');
    });

    it('returns __erroneous__ for undefined input', () => {
      expect(redact(undefined)).toBe('__erroneous__');
    });

    it('returns [Redacted] for empty string', () => {
      expect(redact('')).toBe('[Redacted]');
    });

    it('returns [Redacted] for very short strings that would reveal too much', () => {
      expect(redact('a')).toBe('[Redacted]');
      expect(redact('ab')).toBe('[Redacted]');
      expect(redact('abc')).toBe('[Redacted]');
      expect(redact('abcd')).toBe('[Redacted]');
      expect(redact('abcde')).toBe('[Redacted]');
      expect(redact('abcdef')).toBe('[Redacted]');
    });

    it('returns [Redacted] for "grove" - the specific case mentioned', () => {
      expect(redact('grove')).toBe('[Redacted]');
    });

    it('returns [Redacted] for "hello"', () => {
      expect(redact('hello')).toBe('[Redacted]');
    });

    it('partially redacts longer strings with meaningful middle content', () => {
      expect(redact('abcdefg')).toBe('ab[Redacted]fg');
      expect(redact('abcdefgh')).toBe('ab[Redacted]gh');
      expect(redact('abcdefghi')).toBe('ab[Redacted]hi');
    });

    it('works with custom ends parameter', () => {
      expect(redact('grove', 1)).toBe('g[Redacted]e');
      expect(redact('very-long-string', 3)).toBe('ver[Redacted]ing');
    });

    it('returns [Redacted] for strings too short with custom ends', () => {
      expect(redact('ab', 1)).toBe('[Redacted]'); // middle length = 2-2 = 0 < 3
      expect(redact('abc', 1)).toBe('[Redacted]'); // middle length = 3-2 = 1 < 3
      expect(redact('abcd', 1)).toBe('[Redacted]'); // middle length = 4-2 = 2 < 3
      expect(redact('abcde', 1)).toBe('a[Redacted]e'); // middle length = 5-2 = 3 >= 3
    });
  });

  describe('smear', () => {
    it('returns __erroneous__ for null input', () => {
      expect(smear(null)).toBe('__erroneous__');
    });

    it('returns __erroneous__ for undefined input', () => {
      expect(smear(undefined)).toBe('__erroneous__');
    });

    it('returns [Smeared] for empty string', () => {
      expect(smear('')).toBe('[Smeared]');
    });

    it('returns [Smeared] for strings shorter than or equal to leaveOver', () => {
      expect(smear('a')).toBe('[Smeared]');
      expect(smear('ab')).toBe('[Smeared]');
      expect(smear('abc')).toBe('[Smeared]');
      expect(smear('abcd')).toBe('[Smeared]');
    });

    it('smeares longer strings by replacing middle characters with asterisks', () => {
      expect(smear('hello')).toBe('*ello');
      expect(smear('password')).toBe('****word');
      expect(smear('mySecret123')).toBe('*******t123');
    });

    it('works with custom leaveOver parameter', () => {
      expect(smear('hello', 2)).toBe('***lo');
      expect(smear('password', 3)).toBe('*****ord');
    });
  });

  describe('redactSiteNameFromPath', () => {
    it('redacts site names in REST API paths', () => {
      expect(redactSiteNameFromPath('/sites/my-site/_api/web/lists')).toBe(
        '/sites/my[Redacted]te/_api/web/lists',
      );
      expect(redactSiteNameFromPath('/sites/anotherSite/Documents')).toBe(
        '/sites/an[Redacted]te/Documents',
      );
    });

    it('leaves GUID-like site names untouched (handled by smearSiteIdFromPath)', () => {
      const guidPath = '/sites/a1b2c3d4-e5f6-7890-abcd-ef1234567890/_api/web';
      expect(redactSiteNameFromPath(guidPath)).toBe(guidPath);
    });

    it('handles multiple site names in path', () => {
      expect(redactSiteNameFromPath('/sites/site1/subsite/site2/page')).toBe(
        '/sites/[Redacted]/subsite/site2/page',
      );
    });

    it('handles paths without site names', () => {
      expect(redactSiteNameFromPath('/_api/web/lists')).toBe('/_api/web/lists');
      expect(redactSiteNameFromPath('/graph/me')).toBe('/graph/me');
    });

    it('handles edge cases', () => {
      expect(redactSiteNameFromPath('/sites//_api/web')).toBe('/sites//_api/web');
      expect(redactSiteNameFromPath('/sites/a/_api/web')).toBe('/sites/[Redacted]/_api/web');
    });
  });

  describe('smearSiteIdFromPath', () => {
    it('smeares GUID site IDs in Graph API paths', () => {
      expect(smearSiteIdFromPath('/sites/a1b2c3d4-e5f6-7890-abcd-ef1234567890/drive')).toBe(
        '/sites/********-****-****-****-********7890/drive',
      );
      expect(smearSiteIdFromPath('/sites/b2c3d4e5-f6a7-8910-bcde-f23456789012/root')).toBe(
        '/sites/********-****-****-****-********9012/root',
      );
    });

    it('handles site IDs at end of path', () => {
      expect(smearSiteIdFromPath('/sites/a1b2c3d4-e5f6-7890-abcd-ef1234567890')).toBe(
        '/sites/********-****-****-****-********7890',
      );
    });

    it('leaves non-GUID site names untouched (handled by redactSiteNameFromPath)', () => {
      const siteNamePath = '/sites/my-site/_api/web';
      expect(smearSiteIdFromPath(siteNamePath)).toBe(siteNamePath);
    });

    it('handles multiple GUIDs in path', () => {
      expect(
        smearSiteIdFromPath(
          '/sites/a1b2c3d4-e5f6-7890-abcd-ef1234567890/sub/b2c3d4e5-f6a7-8910-bcde-f23456789012',
        ),
      ).toBe(
        '/sites/********-****-****-****-********7890/sub/b2c3d4e5-f6a7-8910-bcde-f23456789012',
      );
    });

    it('handles paths without site IDs', () => {
      expect(smearSiteIdFromPath('/_api/web/lists')).toBe('/_api/web/lists');
      expect(smearSiteIdFromPath('/graph/me')).toBe('/graph/me');
    });

    it('ignores invalid GUID formats', () => {
      expect(smearSiteIdFromPath('/sites/not-a-guid/_api/web')).toBe('/sites/not-a-guid/_api/web');
      expect(smearSiteIdFromPath('/sites/123-456-789/_api/web')).toBe(
        '/sites/123-456-789/_api/web',
      );
    });
  });

  describe('concealIngestionKey', () => {
    it('smeares siteId in standard ingestion key format', () => {
      expect(concealIngestionKey('a1b2c3d4-e5f6-7890-abcd-ef1234567890/item123')).toBe(
        '********-****-****-****-********7890/item123',
      );
      expect(concealIngestionKey('site-guid/folder1/folder2/file.pdf')).toBe(
        '****-guid/folder1/folder2/file.pdf',
      );
    });

    it('handles ingestion keys with only siteId', () => {
      expect(concealIngestionKey('a1b2c3d4-e5f6-7890-abcd-ef1234567890')).toBe(
        '********-****-****-****-********7890',
      );
    });

    it('smeares entire key if format is unexpected', () => {
      expect(concealIngestionKey('not-a-standard-format')).toBe('***-*-********-**rmat');
      expect(concealIngestionKey('')).toBe('[Smeared]');
      expect(concealIngestionKey('short')).toBe('*hort');
    });

    it('handles edge cases', () => {
      expect(concealIngestionKey('/item123')).toBe('/***m123'); // Empty siteId
      expect(concealIngestionKey('siteId/')).toBe('**teId/'); // Empty item path
      expect(concealIngestionKey('/')).toBe('[Smeared]'); // Just separator
    });

    it('handles complex paths', () => {
      expect(
        concealIngestionKey('a1b2c3d4-e5f6-7890-abcd-ef1234567890/folder/subfolder/file.txt'),
      ).toBe('********-****-****-****-********7890/folder/subfolder/file.txt');
    });
  });

  describe('concealLogs', () => {
    it('returns true when policy is "conceal"', () => {
      const mockConfigService = {
        get: (_key: string, _options: { infer: true }) => 'conceal' as const,
      };
      expect(shouldConcealLogs(mockConfigService)).toBe(true);
    });

    it('returns false when policy is "disclose"', () => {
      const mockConfigService = {
        get: (_key: string, _options: { infer: true }) => 'disclose' as const,
      };
      expect(shouldConcealLogs(mockConfigService)).toBe(false);
    });

    it('calls config service with correct parameters', () => {
      let capturedKey: string | undefined;
      let capturedOptions: { infer: true } | undefined;

      const mockConfigService = {
        get: (key: string, options: { infer: true }) => {
          capturedKey = key;
          capturedOptions = options;
          return 'conceal' as const;
        },
      };

      shouldConcealLogs(mockConfigService);
      expect(capturedKey).toBe('app.logsDiagnosticsDataPolicy');
      expect(capturedOptions).toEqual({ infer: true });
    });
  });
});
