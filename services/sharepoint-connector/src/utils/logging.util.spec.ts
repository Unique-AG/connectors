import { ConfigService } from '@nestjs/config';
import { describe, expect, it } from 'vitest';
import type { Config } from '../config';
import {
  shouldConcealLogs,
  smear,
  smearSiteIdFromPath,
  smearSiteNameFromPath,
} from './logging.util';

describe('logging utilities', () => {
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

    it('returns [Smeared] for strings that would star fewer than 3 characters', () => {
      expect(smear('hello')).toBe('[Smeared]');
      expect(smear('world')).toBe('[Smeared]');
    });

    it('smeares longer strings by replacing middle characters with asterisks', () => {
      expect(smear('password')).toBe('****word');
      expect(smear('mySecret123')).toBe('*******t123');
      expect(smear('verylongstring')).toBe('**********ring');
    });

    it('works with custom leaveOver parameter', () => {
      expect(smear('hello', 2)).toBe('***lo');
      expect(smear('password', 3)).toBe('*****ord');
    });
  });

  describe('smearSiteNameFromPath', () => {
    it('smears site names in REST API paths', () => {
      expect(smearSiteNameFromPath('/sites/my-site/_api/web/lists')).toBe(
        '/sites/**-site/_api/web/lists',
      );
      expect(smearSiteNameFromPath('/sites/anotherSite/Documents')).toBe(
        '/sites/*******Site/Documents',
      );
    });

    it('leaves GUID-like site names untouched (handled by smearSiteIdFromPath)', () => {
      const guidPath = '/sites/a1b2c3d4-e5f6-7890-abcd-ef1234567890/_api/web';
      expect(smearSiteNameFromPath(guidPath)).toBe(guidPath);
    });

    it('handles multiple site names in path', () => {
      expect(smearSiteNameFromPath('/sites/site1/subsite/site2/page')).toBe(
        '/sites/[Smeared]/subsite/site2/page',
      );
    });

    it('handles paths without site names', () => {
      expect(smearSiteNameFromPath('/_api/web/lists')).toBe('/_api/web/lists');
      expect(smearSiteNameFromPath('/graph/me')).toBe('/graph/me');
    });

    it('handles edge cases', () => {
      expect(smearSiteNameFromPath('/sites//_api/web')).toBe('/sites//_api/web');
      expect(smearSiteNameFromPath('/sites/a/_api/web')).toBe('/sites/[Smeared]/_api/web');
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

    it('leaves non-GUID site names untouched (handled by smearSiteNameFromPath)', () => {
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

  describe('concealLogs', () => {
    it('returns true when policy is "conceal"', () => {
      const mockConfigService = {
        get: (_key: string, _options: { infer: true }) => 'conceal' as const,
      } as ConfigService<Config, true>;
      expect(shouldConcealLogs(mockConfigService)).toBe(true);
    });

    it('returns false when policy is "disclose"', () => {
      const mockConfigService = {
        get: (_key: string, _options: { infer: true }) => 'disclose' as const,
      } as ConfigService<Config, true>;
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
      } as ConfigService<Config, true>;

      shouldConcealLogs(mockConfigService);
      expect(capturedKey).toBe('app.logsDiagnosticsDataPolicy');
      expect(capturedOptions).toEqual({ infer: true });
    });
  });
});
