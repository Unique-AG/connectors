import { isNullish } from 'remeda';
import { Smeared } from 'src/utils/smeared';
import { z } from 'zod';
import {
  type PartialSiteConfig,
  type SiteConfig,
  SiteConfigSchema,
  type SiteDefaults,
} from './sharepoint.schema';

/**
 * "set" means: not undefined, and (for strings including Smeared) not empty/whitespace after trim.
 * Numbers and other non-string values are considered set whenever they are not undefined.
 */
function isSet<T>(value: T | undefined): value is T {
  if (value instanceof Smeared) {
    return isSet(value.value);
  }

  if (value === undefined) {
    return false;
  }
  if (typeof value === 'string' && value.trim() === '') {
    return false;
  }
  return true;
}

function coalesce<T>(perSite: T | undefined, fromDefaults: T | undefined): T | undefined {
  return isSet(perSite) ? perSite : fromDefaults;
}

const REQUIRED_AFTER_MERGE = [
  'ingestionMode',
  'scopeId',
  'syncMode',
] as const satisfies readonly (keyof SiteConfig)[];

export function mergeSiteWithDefaults(
  partialSite: PartialSiteConfig,
  siteDefaults: SiteDefaults,
  rowIdentifier: string,
): SiteConfig {
  const merged: Record<keyof SiteConfig, unknown> = {
    siteId: partialSite.siteId,
    syncColumnName: coalesce(partialSite.syncColumnName, siteDefaults.syncColumnName),
    ingestionMode: coalesce(partialSite.ingestionMode, siteDefaults.ingestionMode),
    scopeId: coalesce(partialSite.scopeId, siteDefaults.scopeId),
    maxFilesToIngest: coalesce(partialSite.maxFilesToIngest, siteDefaults.maxFilesToIngest),
    storeInternally: coalesce(partialSite.storeInternally, siteDefaults.storeInternally),
    syncStatus: coalesce(partialSite.syncStatus, siteDefaults.syncStatus),
    syncMode: coalesce(partialSite.syncMode, siteDefaults.syncMode),
    permissionsInheritanceMode: coalesce(
      partialSite.permissionsInheritanceMode,
      siteDefaults.permissionsInheritanceMode,
    ),
    subsitesScan: coalesce(partialSite.subsitesScan, siteDefaults.subsitesScan),
  };

  // We separately check the fields required after merge because it's apparently problematic to
  // properly get info that fields are missing and which one from Zod issues.
  const missingFields = REQUIRED_AFTER_MERGE.filter((field) => isNullish(merged[field]));
  if (missingFields.length > 0) {
    throw new Error(formatMissingFieldsMessage(rowIdentifier, missingFields));
  }

  // We have to cast to string because that's what schema expects, but we do it here instead of in
  // the merged object to not accidentally log the value.
  const result = SiteConfigSchema.safeParse({ ...merged, siteId: partialSite.siteId.value });
  if (result.success) {
    return result.data;
  }

  throw new Error(`${rowIdentifier}: invalid configuration: ${z.prettifyError(result.error)}`);
}

function formatMissingFieldsMessage(rowIdentifier: string, fields: readonly string[]): string {
  const fieldList = fields.map((f) => `'${f}'`).join(', ');
  const verb = fields.length === 1 ? 'is' : 'are';
  const possessiveVerb = fields.length === 1 ? 'has' : 'have';
  return (
    `${rowIdentifier}: required field(s) ${fieldList} ${verb} not set per-site ` +
    `and ${possessiveVerb} no deployment default`
  );
}
