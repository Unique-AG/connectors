import { Injectable, Logger } from '@nestjs/common';
import { entries, filter, forEach, groupBy, isNonNullish, map, pipe } from 'remeda';
import { isAutoScope, isFixedScope, type SiteConfig } from '../config/sharepoint.schema';

@Injectable()
export class DeduplicateSitesQuery {
  private readonly logger = new Logger(DeduplicateSitesQuery.name);

  public execute(sites: SiteConfig[]): SiteConfig[] {
    const dedupedByScope = this.deduplicateByScopeId(sites);
    return this.deduplicateBySiteId(dedupedByScope);
  }

  private deduplicateByScopeId(sites: SiteConfig[]): SiteConfig[] {
    // `auto` rows have no determined scopeId yet at this time as they are resolved at sync time.
    // We pass them through unchanged and rely on per-site checks.
    // Walk the input once preserving original order so that the subsequent
    // deduplicateBySiteId pass keeps first-occurrence-wins semantics across the operator's config.
    const seenFixedScopeIds = new Set<string>();
    const filteredScopeIds: Record<string, SiteConfig[]> = {};
    const deduplicatedSites = sites.flatMap((site) => {
      if (isAutoScope(site.scopeId)) {
        return [site];
      }
      const fixedScopeId = site.scopeId.scopeId;
      if (seenFixedScopeIds.has(fixedScopeId)) {
        filteredScopeIds[fixedScopeId] ??= [];
        filteredScopeIds[fixedScopeId].push(site);
        return [];
      }
      seenFixedScopeIds.add(fixedScopeId);
      return [site];
    });

    pipe(
      filteredScopeIds,
      entries(),
      forEach(([scopeId, sites]) => this.logDuplicateScopeId(scopeId, sites)),
    );

    return deduplicatedSites;
  }

  private logDuplicateScopeId(
    scopeId: string,
    sitesWithSameScopeId: ReadonlyArray<SiteConfig>,
  ): void {
    this.logger.error('DUPLICATE SCOPE ID DETECTED!');
    this.logger.error(`ScopeId: ${scopeId} is configured for multiple sites:`);

    for (const [index, site] of sitesWithSameScopeId.entries()) {
      const status = index === 0 ? 'WILL SYNC - first occurrence' : 'SKIPPED - duplicate scopeId';
      this.logger.error(`  - siteId: ${site.siteId} (${status})`);
    }
    this.logger.error('Only the first site will be synchronized.');
  }

  private deduplicateBySiteId(sites: SiteConfig[]): SiteConfig[] {
    return pipe(
      sites,
      groupBy((site) => site.siteId.value),
      entries(),
      forEach(([siteId, sites]) => {
        if (sites.length > 1) {
          this.logDuplicateSiteId(siteId, sites);
        }
      }),
      map(([, sites]) => sites[0]), // get only the first site from the list of sites
      filter(isNonNullish), // If for whatever reason a group is empty, we filter it here
    );
  }

  private logDuplicateSiteId(siteId: string, sitesWithSameSiteId: ReadonlyArray<SiteConfig>): void {
    this.logger.error('DUPLICATE SITE ID DETECTED!');
    this.logger.error(`SiteId: ${siteId} is configured for multiple rows:`);

    for (const [index, site] of sitesWithSameSiteId.entries()) {
      const status = index === 0 ? 'WILL SYNC - first occurrence' : 'SKIPPED - duplicate siteId';
      const scopeDescriptor = isFixedScope(site.scopeId)
        ? `fixed scopeId=${site.scopeId.scopeId}`
        : `auto parentScopeId=${site.scopeId.parentScopeId}`;
      this.logger.error(`  - ${scopeDescriptor} (${status})`);
    }
    this.logger.error('Only the first row will be synchronized.');
  }
}
