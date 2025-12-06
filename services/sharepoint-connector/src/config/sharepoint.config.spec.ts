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
    it('rejects single invalid UUID', () => {
      const config = {
        ...validConfigBase,
        siteIds: 'invalid-uuid',
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
      try {
        SharepointConfigSchema.parse(config);
      } catch (error) {
        if (error instanceof z.ZodError) {
          expect(error.issues).toHaveLength(1);
          expect(error.issues?.[0]?.path).toEqual(['siteIds', 0]);
          expect(error.issues?.[0]?.message).toBe('Each site ID must be a valid UUIDv4');
        } else {
          throw error;
        }
      }
    });

    it('rejects multiple invalid UUIDs with position information', () => {
      const config = {
        ...validConfigBase,
        siteIds: 'invalid-1,invalid-2,also-invalid',
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
      try {
        SharepointConfigSchema.parse(config);
      } catch (error) {
        if (error instanceof z.ZodError) {
          expect(error.issues).toHaveLength(3);
          expect(error.issues?.[0]?.path).toEqual(['siteIds', 0]);
          expect(error.issues?.[1]?.path).toEqual(['siteIds', 1]);
          expect(error.issues?.[2]?.path).toEqual(['siteIds', 2]);
          expect(error.issues?.[0]?.message).toBe('Each site ID must be a valid UUIDv4');
        } else {
          throw error;
        }
      }
    });

    it('rejects mixed valid and invalid UUIDs', () => {
      const config = {
        ...validConfigBase,
        siteIds:
          '550e8400-e29b-41d4-a716-446655440000,invalid-uuid,550e8400-e29b-41d4-a716-446655440001',
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
      try {
        SharepointConfigSchema.parse(config);
      } catch (error) {
        if (error instanceof z.ZodError) {
          expect(error.issues).toHaveLength(1);
          expect(error.issues?.[0]?.path).toEqual(['siteIds', 1]);
          expect(error.issues?.[0]?.message).toBe('Each site ID must be a valid UUIDv4');
        } else {
          throw error;
        }
      }
    });

    it('rejects UUIDv3 format', () => {
      const config = {
        ...validConfigBase,
        siteIds: 'a3bb189e-8bf9-3888-9912-ace4e6543002', // UUIDv3
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
      try {
        SharepointConfigSchema.parse(config);
      } catch (error) {
        if (error instanceof z.ZodError) {
          expect(error.issues).toHaveLength(1);
          expect(error.issues?.[0]?.path).toEqual(['siteIds', 0]);
          expect(error.issues?.[0]?.message).toBe('Each site ID must be a valid UUIDv4');
        } else {
          throw error;
        }
      }
    });

    it('rejects UUID with wrong version', () => {
      const config = {
        ...validConfigBase,
        siteIds: '550e8400-e29b-11d4-a716-446655440000', // UUIDv1
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
      try {
        SharepointConfigSchema.parse(config);
      } catch (error) {
        if (error instanceof z.ZodError) {
          expect(error.issues).toHaveLength(1);
          expect(error.issues?.[0]?.path).toEqual(['siteIds', 0]);
          expect(error.issues?.[0]?.message).toBe('Each site ID must be a valid UUIDv4');
        } else {
          throw error;
        }
      }
    });

    it('rejects UUID with invalid variant', () => {
      const config = {
        ...validConfigBase,
        siteIds: '550e8400-e29b-41d4-c716-446655440000', // Invalid variant (c instead of 8-9,a-f)
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
      try {
        SharepointConfigSchema.parse(config);
      } catch (error) {
        if (error instanceof z.ZodError) {
          expect(error.issues).toHaveLength(1);
          expect(error.issues?.[0]?.path).toEqual(['siteIds', 0]);
          expect(error.issues?.[0]?.message).toBe('Each site ID must be a valid UUIDv4');
        } else {
          throw error;
        }
      }
    });

    it('filters out empty entries but validates remaining ones', () => {
      const config = {
        ...validConfigBase,
        siteIds: ',550e8400-e29b-41d4-a716-446655440000,,invalid-uuid,',
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
      try {
        SharepointConfigSchema.parse(config);
      } catch (error) {
        if (error instanceof z.ZodError) {
          expect(error.issues).toHaveLength(1);
          expect(error.issues?.[0]?.path).toEqual(['siteIds', 1]);
          expect(error.issues?.[0]?.message).toBe('Each site ID must be a valid UUIDv4');
        } else {
          throw error;
        }
      }
    });
  });
});
