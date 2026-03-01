import { ConfigService } from '@nestjs/config';
import { describe, expect, it } from 'vitest';
import type { Config } from '../config';
import { shouldConcealLogs, smear, smearSiteNameFromPath } from './logging.util';

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
    });

    it('smears multi-segment subsite names in REST API paths', () => {
      expect(smearSiteNameFromPath('/sites/WealthManagement/WMSub1/_api/web/sitegroups')).toBe(
        '/sites/************ment/[Smeared]/_api/web/sitegroups',
      );
    });

    it('smears deeply nested subsite names in REST API paths', () => {
      expect(
        smearSiteNameFromPath('/sites/WealthManagement/WMSub1/Nested/_api/web/sitegroups'),
      ).toBe('/sites/************ment/[Smeared]/[Smeared]/_api/web/sitegroups');
    });

    it('leaves GUID-like site names untouched (handled by smearSiteIdFromPath)', () => {
      const guidPath = '/sites/a1b2c3d4-e5f6-7890-abcd-ef1234567890/_api/web';
      expect(smearSiteNameFromPath(guidPath)).toBe(guidPath);
    });

    it('leaves paths without /_api/ untouched', () => {
      expect(smearSiteNameFromPath('/sites/site1/Documents/page')).toBe(
        '/sites/site1/Documents/page',
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
