import { ConfigService } from '@nestjs/config';
import { describe, expect, it } from 'vitest';
import type { Config } from '../config';
import {
  concealIngestionKey,
  redact,
  redactAllValues,
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
      expect(concealIngestionKey('short')).toBe('[Smeared]');
    });

    it('handles edge cases', () => {
      expect(concealIngestionKey('/item123')).toBe('/***m123'); // Empty siteId
      expect(concealIngestionKey('siteId/')).toBe('[Smeared]/'); // Empty item path
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

  describe('redactAllValues', () => {
    it('redacts primitive string values', () => {
      expect(redactAllValues('sensitive-data')).toBe('***');
      expect(redactAllValues('')).toBe('***');
      expect(redactAllValues('hello world')).toBe('***');
    });

    it('redacts primitive number values', () => {
      expect(redactAllValues(42)).toBe('***');
      expect(redactAllValues(0)).toBe('***');
      expect(redactAllValues(-123.45)).toBe('***');
      expect(redactAllValues(NaN)).toBe('***');
      expect(redactAllValues(Infinity)).toBe('***');
    });

    it('redacts primitive boolean values', () => {
      expect(redactAllValues(true)).toBe('***');
      expect(redactAllValues(false)).toBe('***');
    });

    it('preserves null and undefined values', () => {
      expect(redactAllValues(null)).toBe(null);
      expect(redactAllValues(undefined)).toBe(undefined);
    });

    it('redacts bigint values', () => {
      expect(redactAllValues(BigInt(123))).toBe('***');
    });

    it('redacts symbol values', () => {
      expect(redactAllValues(Symbol('test'))).toBe('***');
    });

    it('redacts simple objects with primitive values', () => {
      const input = {
        name: 'John Doe',
        age: 30,
        email: 'john@example.com',
        isActive: true,
      };

      const expected = {
        name: '***',
        age: '***',
        email: '***',
        isActive: '***',
      };

      expect(redactAllValues(input)).toEqual(expected);
    });

    it('redacts nested objects', () => {
      const input = {
        user: {
          personal: {
            firstName: 'John',
            lastName: 'Doe',
            ssn: '123-45-6789',
          },
          contact: {
            email: 'john@example.com',
            phone: '555-0123',
          },
        },
        metadata: {
          createdAt: '2023-01-01',
          version: 1.0,
        },
      };

      const expected = {
        user: {
          personal: {
            firstName: '***',
            lastName: '***',
            ssn: '***',
          },
          contact: {
            email: '***',
            phone: '***',
          },
        },
        metadata: {
          createdAt: '***',
          version: '***',
        },
      };

      expect(redactAllValues(input)).toEqual(expected);
    });

    it('redacts arrays of primitives', () => {
      const input = ['secret1', 'secret2', 123, true, null, undefined];
      const expected = ['***', '***', '***', '***', null, undefined];

      expect(redactAllValues(input)).toEqual(expected);
    });

    it('redacts arrays of objects', () => {
      const input = [
        { name: 'Alice', secret: 'password123' },
        { name: 'Bob', secret: 'letmein' },
      ];

      const expected = [
        { name: '***', secret: '***' },
        { name: '***', secret: '***' },
      ];

      expect(redactAllValues(input)).toEqual(expected);
    });

    it('redacts mixed arrays with nested structures', () => {
      const input = [
        'simple string',
        { key: 'value', nested: { deep: 'secret' } },
        [1, 2, { inner: 'data' }],
        null,
        undefined,
      ];

      const expected = [
        '***',
        { key: '***', nested: { deep: '***' } },
        ['***', '***', { inner: '***' }],
        null,
        undefined,
      ];

      expect(redactAllValues(input)).toEqual(expected);
    });

    it('redacts empty objects and arrays', () => {
      expect(redactAllValues({})).toEqual({});
      expect(redactAllValues([])).toEqual([]);
    });

    it('preserves object structure with empty keys', () => {
      const input = {
        '': 'empty key',
        key: '',
        nested: {
          '': 'nested empty key',
        },
      };

      const expected = {
        '': '***',
        key: '***',
        nested: {
          '': '***',
        },
      };

      expect(redactAllValues(input)).toEqual(expected);
    });

    it('handles complex permission-like objects', () => {
      const input = {
        id: '97411c66-13bd-453a-8785-9927a1356307',
        grantedToIdentitiesV2: [
          {
            siteUser: {
              displayName: 'Thomas Hediger',
              email: 'hediger@solira.ch',
              id: '84',
              loginName: 'i:0#.f|membership|hediger_solira.ch#ext#@uniqueapp.onmicrosoft.com',
            },
          },
          {
            user: {
              '@odata.type': '#microsoft.graph.sharePointIdentity',
              displayName: 'Thomas Hediger',
              email: 'hediger@solira.ch',
            },
          },
        ],
        roles: ['read', 'write'],
        metadata: {
          created: '2023-01-01T00:00:00Z',
          modified: '2023-12-01T00:00:00Z',
          version: 1,
        },
      };

      const expected = {
        id: '***',
        grantedToIdentitiesV2: [
          {
            siteUser: {
              displayName: '***',
              email: '***',
              id: '***',
              loginName: '***',
            },
          },
          {
            user: {
              '@odata.type': '***',
              displayName: '***',
              email: '***',
            },
          },
        ],
        roles: ['***', '***'],
        metadata: {
          created: '***',
          modified: '***',
          version: '***',
        },
      };

      expect(redactAllValues(input)).toEqual(expected);
    });

    it('handles objects with symbol keys', () => {
      const symbolKey = Symbol('test');
      const input = {
        [symbolKey]: 'symbol value',
        normalKey: 'normal value',
      };

      const result = redactAllValues(input) as Record<string | symbol, unknown>;

      expect(result[symbolKey]).toBe('***');
      expect(result.normalKey).toBe('***');
      expect(Object.getOwnPropertySymbols(result)).toContain(symbolKey);
    });

    it('redacts Date objects', () => {
      const date = new Date('2023-01-01');
      expect(redactAllValues(date)).toBe('***');
    });

    it('redacts RegExp objects', () => {
      const regex = /test/g;
      expect(redactAllValues(regex)).toBe('***');
    });

    it('redacts function objects', () => {
      const func = () => 'test';
      expect(redactAllValues(func)).toBe('***');
    });

    it('works with JSON.stringify for logging', () => {
      const input = {
        sensitive: 'secret',
        nested: { password: '123456', token: 'abc123' },
      };

      const redacted = redactAllValues(input);
      const json = JSON.stringify(redacted);

      expect(json).toContain('sensitive');
      expect(json).toContain('nested');
      expect(json).toContain('password');
      expect(json).toContain('token');
      expect(json).toContain('"***"');
      expect(json).not.toContain('secret');
      expect(json).not.toContain('123456');
      expect(json).not.toContain('abc123');
    });
  });
});
