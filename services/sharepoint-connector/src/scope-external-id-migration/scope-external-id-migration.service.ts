import { Injectable, Logger } from '@nestjs/common';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { sanitizeError } from '../utils/normalize-error';
import {
  EXTERNAL_ID_PREFIX,
  isLegacyExternalId,
  migrateLegacyExternalId,
  parseLegacyExternalId,
} from '../utils/scope-external-id';
import { createSmeared } from '../utils/smeared';
import { groupScopesByRootSiteId } from './group-scopes-by-root-site-id';

export type ExternalIdMigrationResult =
  | { status: 'no_migration_needed' }
  | { status: 'migration_completed'; migratedCount: number }
  | { status: 'migration_failed'; migratedCount: number; failedCount: number };

const CACHE_TTL_MS = 2 * 60 * 60 * 1000;

interface CacheEntry {
  readonly scopes: Scope[];
  readonly populatedAt: number;
}

@Injectable()
export class ScopeExternalIdMigrationService {
  private readonly logger = new Logger(ScopeExternalIdMigrationService.name);

  // Per-site cache of grouped scopes. When a site is missing from the cache,
  // all scopes are fetched and grouped — populating entries for every site at
  // once. After a successful migration, only the migrated site's entry is
  // evicted (the data changed), while other sites' entries remain valid.
  private readonly siteCache = new Map<string, CacheEntry>();

  public constructor(private readonly uniqueScopesService: UniqueScopesService) {}

  public async migrateIfNeeded(rootSiteId: string): Promise<ExternalIdMigrationResult> {
    const logPrefix = `[ExternalId Migration: ${createSmeared(rootSiteId)}]`;

    try {
      const siteScopes = await this.getScopesForSite(rootSiteId);

      const rootScope = siteScopes.find(
        (s): s is Scope & { externalId: string } =>
          s.externalId !== null && parseLegacyExternalId(s.externalId)?.type === 'root',
      );

      if (!rootScope) {
        this.logger.debug(`${logPrefix} No legacy root scope found, no migration needed`);
        return { status: 'no_migration_needed' };
      }

      const children = siteScopes.filter((s) => s.id !== rootScope.id);

      this.logger.log(`${logPrefix} Found ${children.length} children and 1 root scope to migrate`);

      let migratedCount = 0;
      let failedCount = 0;

      // Migrate children first. The root externalId is the definitive marker
      // that migration for this site is complete, so it must stay in legacy
      // format until every child succeeds — otherwise the next sync would see
      // a new-format root and skip retrying the stranded legacy children.
      for (const scope of children) {
        if (!scope.externalId || !isLegacyExternalId(scope.externalId)) {
          continue;
        }

        try {
          const newExternalId = migrateLegacyExternalId(
            rootSiteId,
            createSmeared(scope.externalId),
          );
          await this.uniqueScopesService.updateScopeExternalId(scope.id, newExternalId);
          migratedCount++;
        } catch (error) {
          this.logger.warn({
            msg: `${logPrefix} Failed to migrate scope ${scope.id}`,
            error: sanitizeError(error),
          });
          failedCount++;
        }
      }

      if (failedCount > 0) {
        // Leave the root in legacy format so the next sync retries the failed
        // children. Evict the cache since at least one child's externalId changed.
        this.siteCache.delete(rootSiteId);
        return { status: 'migration_failed', migratedCount, failedCount };
      }

      try {
        const newRootExternalId = migrateLegacyExternalId(
          rootSiteId,
          createSmeared(rootScope.externalId),
        );
        await this.uniqueScopesService.updateScopeExternalId(rootScope.id, newRootExternalId);
        migratedCount++;
      } catch (error) {
        this.logger.warn({
          msg: `${logPrefix} Failed to migrate root scope ${rootScope.id}`,
          error: sanitizeError(error),
        });
        failedCount++;
      }

      this.siteCache.delete(rootSiteId);

      if (failedCount > 0) {
        return { status: 'migration_failed', migratedCount, failedCount };
      }

      this.logger.log(`${logPrefix} Migration completed, ${migratedCount} scopes migrated`);
      return { status: 'migration_completed', migratedCount };
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Migration failed`,
        error: sanitizeError(error),
      });
      return { status: 'migration_failed', migratedCount: 0, failedCount: 0 };
    }
  }

  private async getScopesForSite(rootSiteId: string): Promise<Scope[]> {
    const cached = this.siteCache.get(rootSiteId);
    if (cached && Date.now() - cached.populatedAt < CACHE_TTL_MS) {
      return cached.scopes;
    }

    const allScopes = await this.uniqueScopesService.listScopesByExternalIdPrefix(
      createSmeared(EXTERNAL_ID_PREFIX),
    );

    const grouped = groupScopesByRootSiteId(allScopes);
    const now = Date.now();

    for (const [siteId, scopes] of grouped) {
      this.siteCache.set(siteId, { scopes, populatedAt: now });
    }

    return grouped.get(rootSiteId) ?? [];
  }
}
