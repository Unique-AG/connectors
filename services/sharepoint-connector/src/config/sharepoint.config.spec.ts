import { describe, expect, it } from 'vitest';
import { IngestionMode } from '../constants/ingestion.constants';
import { StoreInternallyMode } from '../constants/store-internally-mode.enum';
import { SharepointConfigSchema } from './sharepoint.schema';

describe('SharepointConfigSchema', () => {
  const validBaseConfig = {
    tenantId: '12345678-1234-1234-1234-123456789abc',
    baseUrl: 'https://company.sharepoint.com',
    graphApiRateLimitPerMinute: 600,
    sitesSource: 'config_file' as const,
    sites: [
      {
        siteId: '87654321-4321-4321-8321-cba987654321',
        syncColumnName: 'FinanceGPTKnowledge',
        ingestionMode: IngestionMode.Recursive,
        scopeId: 'scope_test123',
        maxFilesToIngest: 1000,
        storeInternally: StoreInternallyMode.Enabled,
        syncStatus: 'active' as const,
        syncMode: 'content_and_permissions' as const,
        permissionsInheritanceMode: 'inherit_scopes_and_files' as const,
      },
    ],
  };

  describe('valid configurations', () => {
    it('validates oidc auth mode configuration', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).not.toThrow();
      const result = SharepointConfigSchema.parse(config);
      expect(result.auth.mode).toBe('oidc');
    });

    it('validates client-secret auth mode configuration', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'client-secret' as const,
          clientId: 'client-id-123',
          clientSecret: 'secret-123',
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).not.toThrow();
      const result = SharepointConfigSchema.parse(config);
      expect(result.auth.mode).toBe('client-secret');
      if (result.auth.mode === 'client-secret') {
        expect(result.auth.clientId).toBe('client-id-123');
        expect(result.auth.clientSecret).toBeInstanceOf(Object); // Redacted
      }
    });

    it('validates certificate auth mode with SHA1 thumbprint', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'certificate' as const,
          clientId: 'client-id-123',
          thumbprintSha1: 'abcdef1234567890abcdef1234567890abcdef12',
          privateKeyPath: '/path/to/key.pem',
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).not.toThrow();
      const result = SharepointConfigSchema.parse(config);
      expect(result.auth.mode).toBe('certificate');
      if (result.auth.mode === 'certificate') {
        expect(result.auth.thumbprintSha1).toBe('abcdef1234567890abcdef1234567890abcdef12');
      }
    });

    it('validates certificate auth mode with SHA256 thumbprint', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'certificate' as const,
          clientId: 'client-id-123',
          thumbprintSha256:
            'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
          privateKeyPath: '/path/to/key.pem',
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).not.toThrow();
    });

    it('validates configuration with multiple sites', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sitesSource: 'config_file' as const,
        sites: [
          {
            siteId: '87654321-4321-4321-8321-cba987654321',
            syncColumnName: 'FinanceGPTKnowledge',
            ingestionMode: IngestionMode.Recursive,
            scopeId: 'scope_finance',
            syncMode: 'content_and_permissions' as const,
            permissionsInheritanceMode: 'inherit_scopes_and_files' as const,
          },
          {
            siteId: 'abcd1234-5678-4012-8346-789012345678',
            syncColumnName: 'HRKnowledge',
            ingestionMode: IngestionMode.Flat,
            scopeId: 'scope_hr',
            maxFilesToIngest: 500,
            storeInternally: StoreInternallyMode.Disabled,
            syncStatus: 'inactive' as const,
            syncMode: 'content_only' as const,
            permissionsInheritanceMode: 'inherit_scopes_and_files' as const,
          },
        ],
      };

      expect(() => SharepointConfigSchema.parse(config)).not.toThrow();
      const result = SharepointConfigSchema.parse(config);
      if (result.sitesSource === 'config_file') {
        expect(result.sites).toHaveLength(2);
      }
    });

    it('validates sharepoint_list source configuration', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sitesSource: 'sharepoint_list' as const,
        sharepointList: {
          siteId: '87654321-4321-4321-8321-cba987654321',
          listDisplayName: 'Sharepoint Sites to Sync',
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).not.toThrow();
      const result = SharepointConfigSchema.parse(config);
      expect(result.sitesSource).toBe('sharepoint_list');
      if (result.sitesSource === 'sharepoint_list') {
        expect(result.sharepointList.siteId).toBe('87654321-4321-4321-8321-cba987654321');
        expect(result.sharepointList.listDisplayName).toBe('Sharepoint Sites to Sync');
      }
    });
  });

  describe('sites array validation', () => {
    it('requires at least one site', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sitesSource: 'config_file' as const,
        sites: [],
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow(
        'At least one site must be configured',
      );
    });

    it('validates siteId as UUID', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sites: [
          {
            ...validBaseConfig.sites[0],
            siteId: 'not-a-uuid',
          },
        ],
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('validates syncColumnName is string', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sites: [
          {
            ...validBaseConfig.sites[0],
            syncColumnName: 123,
          },
        ],
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('validates ingestionMode enum values', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sites: [
          {
            ...validBaseConfig.sites[0],
            ingestionMode: 'invalid-mode',
          },
        ],
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('validates scopeId is required', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sites: [
          {
            siteId: '87654321-4321-4321-4321-cba987654321',
            syncColumnName: 'FinanceGPTKnowledge',
            ingestionMode: IngestionMode.Recursive,
            syncMode: 'content_and_permissions' as const,
            // missing scopeId
          },
        ],
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('validates maxFilesToIngest is positive integer when provided', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sites: [
          {
            ...validBaseConfig.sites[0],
            maxFilesToIngest: -1,
          },
        ],
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('validates storeInternally enum values', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sites: [
          {
            ...validBaseConfig.sites[0],
            storeInternally: 'invalid-value',
          },
        ],
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('validates syncStatus enum values', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sites: [
          {
            ...validBaseConfig.sites[0],
            syncStatus: 'invalid-status',
          },
        ],
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('validates syncMode enum values', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sites: [
          {
            ...validBaseConfig.sites[0],
            syncMode: 'invalid-mode',
          },
        ],
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });
  });

  describe('site configuration defaults', () => {
    it('applies default values for optional fields', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        sites: [
          {
            siteId: '87654321-4321-4321-8321-cba987654321',
            ingestionMode: IngestionMode.Recursive,
            scopeId: 'scope_test',
            syncMode: 'content_only' as const,
          },
        ],
      };

      const result = SharepointConfigSchema.parse(config);

      // Handle discriminated union
      if (result.sitesSource === 'config_file') {
        expect(result.sites).toHaveLength(1);

        // TypeScript doesn't understand that the schema guarantees at least one site
        // biome-ignore lint/style/noNonNullAssertion: Schema validation ensures array has at least one element
        const site = result.sites[0]!;

        expect(site.syncColumnName).toBe('FinanceGPTKnowledge'); // default value
        expect(site.storeInternally).toBe(StoreInternallyMode.Enabled); // default value
        expect(site.syncStatus).toBe('active'); // default value
        expect(site.permissionsInheritanceMode).toBe('inherit_scopes_and_files'); // default value
        expect(site.maxFilesToIngest).toBeUndefined(); // optional field
      }
    });
  });

  describe('invalid configurations', () => {
    it('rejects missing tenantId', () => {
      const config = {
        ...validBaseConfig,
        tenantId: '',
        auth: {
          mode: 'oidc' as const,
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('rejects invalid baseUrl format', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        baseUrl: 'not-a-url',
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('rejects baseUrl with trailing slash', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        baseUrl: 'https://company.sharepoint.com/',
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow(
        'Base URL must not end with a trailing slash',
      );
    });

    it('rejects negative graphApiRateLimitPerMinute', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'oidc' as const,
        },
        graphApiRateLimitPerMinute: -1,
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('rejects certificate auth without thumbprint', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'certificate' as const,
          clientId: 'client-id-123',
          privateKeyPath: '/path/to/key.pem',
          // missing both thumbprints
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow(
        'Either thumbprintSha1 or thumbprintSha256 has to be provided',
      );
    });

    it('rejects client-secret auth without clientId', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'client-secret' as const,
          clientSecret: 'secret-123',
          // missing clientId
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('rejects client-secret auth without clientSecret', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'client-secret' as const,
          clientId: 'client-id-123',
          // missing clientSecret
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('rejects certificate auth without privateKeyPath', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'certificate' as const,
          clientId: 'client-id-123',
          thumbprintSha1: 'abcdef1234567890abcdef1234567890abcdef12',
          // missing privateKeyPath
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });

    it('rejects invalid hex thumbprint', () => {
      const config = {
        ...validBaseConfig,
        auth: {
          mode: 'certificate' as const,
          clientId: 'client-id-123',
          thumbprintSha1: 'gggggggggggggggggggggggggggggggggggggggg', // invalid hex
          privateKeyPath: '/path/to/key.pem',
        },
      };

      expect(() => SharepointConfigSchema.parse(config)).toThrow();
    });
  });
});
