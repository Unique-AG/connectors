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

export function mergeSiteWithDefaults(
  partialSite: PartialSiteConfig,
  siteDefaults: SiteDefaults,
  rowIdentifier: string,
): SiteConfig {
  const merged = {
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

  const result = SiteConfigSchema.safeParse(merged);
  if (result.success) {
    return result.data;
  }

  throw new Error(buildErrorMessage(rowIdentifier, result.error));
}

function isMissingFieldIssue(issue: z.core.$ZodIssue): boolean {
  return (
    issue.code === 'invalid_type' &&
    issue.path.length > 0 &&
    'received' in issue &&
    issue.received === 'undefined'
  );
}

function buildErrorMessage(rowIdentifier: string, error: z.ZodError): string {
  const missingFields = error.issues
    .filter(isMissingFieldIssue)
    .map((issue) => issue.path.join('.'));

  if (missingFields.length > 0) {
    const fieldList = missingFields.map((f) => `'${f}'`).join(', ');
    const verb = missingFields.length === 1 ? 'is' : 'are';
    const possessiveVerb = missingFields.length === 1 ? 'has' : 'have';
    return (
      `Row ${rowIdentifier}: required field(s) ${fieldList} ${verb} not set per-site ` +
      `and ${possessiveVerb} no deployment default`
    );
  }

  return `Row ${rowIdentifier}: invalid configuration: ${z.prettifyError(error)}`;
}
