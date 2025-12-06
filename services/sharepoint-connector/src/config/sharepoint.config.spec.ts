import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { SharepointConfigSchema } from './sharepoint.config';

describe('SharepointConfigSchema - siteIds validation', () => {
  const validConfigBase = {
    authMode: 'client-secret' as const,
    authClientId: '550e8400-e29b-41d4-a716-446655440000',
    authClientSecret: 'redacted-secret',
    authTenantId: '550e8400-e29b-41d4-a716-446655440001',
    graphApiRateLimitPerMinute: 100,
    baseUrl: 'https://example.sharepoint.com',
  };

  describe('valid UUIDv4 entries', () => {
    it('accepts single valid UUIDv4', () => {
      const config = {
        ...validConfigBase,
        siteIds: '550e8400-e29b-41d4-a716-446655440000',
      };

      const result = SharepointConfigSchema.parse(config);
      expect(result.siteIds).toEqual(['550e8400-e29b-41d4-a716-446655440000']);
    });

    it('accepts multiple valid UUIDv4 entries', () => {
      const config = {
        ...validConfigBase,
        siteIds:
          '550e8400-e29b-41d4-a716-446655440000,550e8400-e29b-41d4-a716-446655440001,550e8400-e29b-41d4-a716-446655440002',
      };

      const result = SharepointConfigSchema.parse(config);
      expect(result.siteIds).toEqual([
        '550e8400-e29b-41d4-a716-446655440000',
        '550e8400-e29b-41d4-a716-446655440001',
        '550e8400-e29b-41d4-a716-446655440002',
      ]);
    });

    it('accepts UUIDv4 entries with extra whitespace', () => {
      const config = {
        ...validConfigBase,
        siteIds: ' 550e8400-e29b-41d4-a716-446655440000 , 550e8400-e29b-41d4-a716-446655440001 ',
      };

      const result = SharepointConfigSchema.parse(config);
      expect(result.siteIds).toEqual([
        '550e8400-e29b-41d4-a716-446655440000',
        '550e8400-e29b-41d4-a716-446655440001',
      ]);
    });

    it('accepts empty string and returns empty array', () => {
      const config = {
        ...validConfigBase,
        siteIds: '',
      };

      const result = SharepointConfigSchema.parse(config);
      expect(result.siteIds).toEqual([]);
    });

    it('accepts uppercase UUIDv4 entries', () => {
      const config = {
        ...validConfigBase,
        siteIds: '550E8400-E29B-41D4-A716-446655440000',
      };

      const result = SharepointConfigSchema.parse(config);
      expect(result.siteIds).toEqual(['550E8400-E29B-41D4-A716-446655440000']);
    });
  });

  describe('invalid UUIDv4 entries', () => {
    const expectSiteIdsValidationError = ({
      config,
      errorIndexes,
    }: {
      config: unknown;
      errorIndexes: number[];
    }) => {
      const expectedMessage = 'Each site ID must be a valid UUIDv4';
      expect(() => SharepointConfigSchema.parse(config)).toThrow();
      try {
        SharepointConfigSchema.parse(config);
      } catch (error) {
        if (error instanceof z.ZodError) {
          expect(error.issues).toHaveLength(errorIndexes.length);
          errorIndexes.forEach((expectedIndex, i) => {
            expect(error.issues?.[i]?.path).toEqual(['siteIds', expectedIndex]);
            expect(error.issues?.[i]?.message).toBe(expectedMessage);
          });
        } else {
          throw error;
        }
      }
    };

    it('rejects single invalid UUID', () => {
      const config = {
        ...validConfigBase,
        siteIds: 'invalid-uuid',
      };

      expectSiteIdsValidationError({ config, errorIndexes: [0] });
    });

    it('rejects multiple invalid UUIDs with position information', () => {
      const config = {
        ...validConfigBase,
        siteIds: 'invalid-1,invalid-2,also-invalid',
      };

      expectSiteIdsValidationError({ config, errorIndexes: [0, 1, 2] });
    });

    it('rejects mixed valid and invalid UUIDs', () => {
      const config = {
        ...validConfigBase,
        siteIds:
          '550e8400-e29b-41d4-a716-446655440000,invalid-uuid,550e8400-e29b-41d4-a716-446655440001',
      };

      expectSiteIdsValidationError({ config, errorIndexes: [1] });
    });

    it('rejects UUIDv3 format', () => {
      const config = {
        ...validConfigBase,
        siteIds: 'a3bb189e-8bf9-3888-9912-ace4e6543002', // UUIDv3
      };

      expectSiteIdsValidationError({ config, errorIndexes: [0] });
    });

    it('rejects UUID with wrong version', () => {
      const config = {
        ...validConfigBase,
        siteIds: '550e8400-e29b-11d4-a716-446655440000', // UUIDv1
      };

      expectSiteIdsValidationError({ config, errorIndexes: [0] });
    });

    it('rejects UUID with invalid variant', () => {
      const config = {
        ...validConfigBase,
        siteIds: '550e8400-e29b-41d4-c716-446655440000', // Invalid variant (c instead of 8-9,a-f)
      };

      expectSiteIdsValidationError({ config, errorIndexes: [0] });
    });

    it('filters out empty entries but validates remaining ones', () => {
      const config = {
        ...validConfigBase,
        siteIds: ',550e8400-e29b-41d4-a716-446655440000,,invalid-uuid,',
      };

      expectSiteIdsValidationError({ config, errorIndexes: [1] });
    });
  });
});
