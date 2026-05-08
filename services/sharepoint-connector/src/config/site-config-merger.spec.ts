import { describe, expect, it } from 'vitest';
import { EnabledDisabledMode } from '../constants/enabled-disabled-mode.enum';
import { IngestionMode } from '../constants/ingestion.constants';
import { createSmeared, Smeared } from '../utils/smeared';
import {
  type PartialSiteConfig,
  PartialSiteConfigSchema,
  SiteDefaultsSchema,
} from './sharepoint.schema';
import { mergeSiteWithDefaults } from './site-config-merger';

const SITE_UUID = '87654321-4321-4321-8321-cba987654321';
const ROW_ID = 'row[2]';

const fullSiteDefaults = SiteDefaultsSchema.parse({
  syncColumnName: 'FinanceGPTKnowledge',
  ingestionMode: IngestionMode.Recursive,
  scopeId: 'default-scope',
  storeInternally: EnabledDisabledMode.Enabled,
  syncStatus: 'active',
  syncMode: 'content_only',
  permissionsInheritanceMode: 'inherit_scopes_and_files',
  subsitesScan: EnabledDisabledMode.Enabled,
});

const emptySiteDefaults = SiteDefaultsSchema.parse({});

describe('mergeSiteWithDefaults', () => {
  describe('per-site values vs defaults', () => {
    it('takes the per-site value when it is set', () => {
      const partial = PartialSiteConfigSchema.parse({
        siteId: SITE_UUID,
        syncColumnName: 'CustomCol',
      });

      const result = mergeSiteWithDefaults(partial, fullSiteDefaults, ROW_ID);

      expect(result.syncColumnName).toBe('CustomCol');
    });

    it('falls through to default when per-site value is an empty string', () => {
      const partial: PartialSiteConfig = {
        siteId: createSmeared(SITE_UUID),
        syncColumnName: '',
      };

      const result = mergeSiteWithDefaults(partial, fullSiteDefaults, ROW_ID);

      expect(result.syncColumnName).toBe('FinanceGPTKnowledge');
    });

    it('falls through to default when per-site value is whitespace-only', () => {
      const partial: PartialSiteConfig = {
        siteId: createSmeared(SITE_UUID),
        syncColumnName: '   ',
      };

      const result = mergeSiteWithDefaults(partial, fullSiteDefaults, ROW_ID);

      expect(result.syncColumnName).toBe('FinanceGPTKnowledge');
    });

    it('falls through to default when per-site value is undefined', () => {
      const partial = PartialSiteConfigSchema.parse({
        siteId: SITE_UUID,
      });

      const result = mergeSiteWithDefaults(partial, fullSiteDefaults, ROW_ID);

      expect(result.syncColumnName).toBe('FinanceGPTKnowledge');
    });

    it('treats a falsy-looking but non-empty enum value as set', () => {
      const partial = PartialSiteConfigSchema.parse({
        siteId: SITE_UUID,
        subsitesScan: EnabledDisabledMode.Disabled,
      });

      const result = mergeSiteWithDefaults(partial, fullSiteDefaults, ROW_ID);

      expect(result.subsitesScan).toBe(EnabledDisabledMode.Disabled);
    });
  });

  describe('error handling', () => {
    it('throws including the row identifier and listing missing fields when required fields are absent in both partial and defaults', () => {
      const partial = PartialSiteConfigSchema.parse({ siteId: SITE_UUID });

      expect(() => mergeSiteWithDefaults(partial, emptySiteDefaults, ROW_ID)).toThrow(
        new RegExp(`^${ROW_ID.replace(/[[\]]/g, '\\$&')}: required field\\(s\\)`),
      );
      const error = (() => {
        try {
          mergeSiteWithDefaults(partial, emptySiteDefaults, ROW_ID);
          return undefined;
        } catch (e) {
          return e as Error;
        }
      })();
      expect(error).toBeDefined();
      expect(error?.message).toContain("'ingestionMode'");
      expect(error?.message).toContain("'scopeId'");
      expect(error?.message).toContain("'syncMode'");
      expect(error?.message).toContain('are not set per-site and have no deployment default');
    });

    it('uses singular verbs when exactly one required field is missing', () => {
      const partial = PartialSiteConfigSchema.parse({
        siteId: SITE_UUID,
        ingestionMode: IngestionMode.Recursive,
        syncMode: 'content_only',
      });

      const error = (() => {
        try {
          mergeSiteWithDefaults(partial, emptySiteDefaults, ROW_ID);
          return undefined;
        } catch (e) {
          return e as Error;
        }
      })();
      expect(error).toBeDefined();
      expect(error?.message).toContain("'scopeId'");
      expect(error?.message).toContain('is not set per-site and has no deployment default');
    });

    it('throws with "invalid configuration" wording for an invalid enum value supplied per-site', () => {
      const partial = {
        siteId: createSmeared(SITE_UUID),
        ingestionMode: 'bogus',
        scopeId: 'scope-1',
        syncMode: 'content_only',
      } as unknown as PartialSiteConfig;

      expect(() => mergeSiteWithDefaults(partial, emptySiteDefaults, ROW_ID)).toThrow(
        new RegExp(`^${ROW_ID.replace(/[[\]]/g, '\\$&')}: invalid configuration: `),
      );
      expect(() => mergeSiteWithDefaults(partial, emptySiteDefaults, ROW_ID)).not.toThrow(
        /required field\(s\)/,
      );
    });
  });

  describe('successful merge shape', () => {
    it('succeeds with all required fields set per-site and empty defaults', () => {
      const partial = PartialSiteConfigSchema.parse({
        siteId: SITE_UUID,
        syncColumnName: 'CustomCol',
        ingestionMode: IngestionMode.Recursive,
        scopeId: 'scope-per-site',
        maxFilesToIngest: 500,
        storeInternally: EnabledDisabledMode.Disabled,
        syncStatus: 'inactive',
        syncMode: 'content_and_permissions',
        permissionsInheritanceMode: 'inherit_files',
        subsitesScan: EnabledDisabledMode.Enabled,
      });

      const result = mergeSiteWithDefaults(partial, emptySiteDefaults, ROW_ID);

      expect(result.syncColumnName).toBe('CustomCol');
      expect(result.ingestionMode).toBe(IngestionMode.Recursive);
      expect(result.scopeId).toBe('scope-per-site');
      expect(result.maxFilesToIngest).toBe(500);
      expect(result.storeInternally).toBe(EnabledDisabledMode.Disabled);
      expect(result.syncStatus).toBe('inactive');
      expect(result.syncMode).toBe('content_and_permissions');
      expect(result.permissionsInheritanceMode).toBe('inherit_files');
      expect(result.subsitesScan).toBe(EnabledDisabledMode.Enabled);
      expect(result.siteId).toBeInstanceOf(Smeared);
      expect(result.siteId.value).toBe(SITE_UUID);
    });

    it('returns a Smeared siteId carrying the original UUID after parsing', () => {
      const partial = PartialSiteConfigSchema.parse({ siteId: SITE_UUID });

      const result = mergeSiteWithDefaults(partial, fullSiteDefaults, ROW_ID);

      expect(result.siteId).toBeInstanceOf(Smeared);
      expect(result.siteId.value).toBe(SITE_UUID);
    });
  });
});
