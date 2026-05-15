import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { isFixedScope, type SiteConfig } from '../../config/sharepoint.schema';
import { ScopeExternalIdMigrationService } from '../../scope-external-id-migration/scope-external-id-migration.service';
import { UniqueScopesService } from '../../unique-api/unique-scopes/unique-scopes.service';
import type { Scope } from '../../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../../unique-api/unique-users/unique-users.service';
import { sanitizeError } from '../../utils/normalize-error';
import { buildRootExternalId, isOwnedBySite } from '../../utils/scope-external-id';
import { Smeared, smearPath } from '../../utils/smeared';
import { RootScopeMigrationService } from '../root-scope-migration.service';
import { CreateRootScopeCommand } from './create-root-scope.command';
import { FindRootScopeQuery } from './find-root-scope.query';
import { ResolveScopePathCommand } from './resolve-scope-path.command';

export interface InitializeRootScopeResult {
  rootScopeId: string;
  serviceUserId: string;
  rootPath: Smeared;
  isInitialSync: boolean;
}

@Injectable()
export class InitializeRootScopeCommand {
  private readonly logger = new Logger(InitializeRootScopeCommand.name);

  public constructor(
    private readonly findRootScopeQuery: FindRootScopeQuery,
    private readonly createRootScopeCommand: CreateRootScopeCommand,
    private readonly resolveScopePathCommand: ResolveScopePathCommand,
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly uniqueUsersService: UniqueUsersService,
    private readonly rootScopeMigrationService: RootScopeMigrationService,
    private readonly scopeExternalIdMigrationService: ScopeExternalIdMigrationService,
  ) {}

  public async execute(
    siteConfig: SiteConfig,
    siteName: Smeared,
  ): Promise<InitializeRootScopeResult> {
    const { rootScopeId, precomputedRootPath } = await this.resolveRootScopeId(
      siteConfig,
      siteName,
    );

    const siteId = siteConfig.siteId;
    const logPrefix = `[RootScopeId: ${rootScopeId}]`;

    const userId = await this.uniqueUsersService.getCurrentUserId();
    assert.ok(userId, 'User ID must be available');

    this.logger.log(`${logPrefix} Initializing root scope (Mode: ${siteConfig.ingestionMode})`);

    await this.uniqueScopesService.createScopeAccesses(rootScopeId, [
      { type: 'MANAGE', entityId: userId, entityType: 'USER' },
      { type: 'READ', entityId: userId, entityType: 'USER' },
      { type: 'WRITE', entityId: userId, entityType: 'USER' },
    ]);

    const rootScope = await this.uniqueScopesService.getScopeById(rootScopeId);
    assert.ok(rootScope, `Root scope with ID ${rootScopeId} not found`);

    const isValid = this.isValidScopeOwnership(rootScope, siteId);
    assert.ok(
      isValid,
      `Root scope ${rootScopeId} is owned by a different site. This scope cannot be synced by this site.`,
    );

    const externalIdMigrationResult = await this.scopeExternalIdMigrationService.migrateIfNeeded(
      siteId.value,
    );
    if (externalIdMigrationResult.status === 'migration_failed') {
      throw new Error(
        `${logPrefix} Scope externalId migration failed: ` +
          `migrated=${externalIdMigrationResult.migratedCount}, ` +
          `failed=${externalIdMigrationResult.failedCount}`,
      );
    }

    const isInitialSync = !rootScope.externalId;

    if (isInitialSync) {
      const migrationResult = await this.rootScopeMigrationService.migrateIfNeeded(
        rootScopeId,
        siteId,
      );
      if (migrationResult.status === 'migration_failed') {
        throw new Error(`Root scope migration failed: ${migrationResult.error}`);
      }

      const externalId = buildRootExternalId(siteId.value);
      try {
        const updatedScope = await this.uniqueScopesService.updateScopeExternalId(
          rootScopeId,
          externalId,
        );
        rootScope.externalId = updatedScope.externalId;
        this.logger.debug(
          `${logPrefix} Claimed root scope ${rootScopeId} with externalId: ${externalId}`,
        );
      } catch (error) {
        this.logger.warn({
          msg: `${logPrefix} Failed to claim root scope ${rootScopeId} with externalId: ${externalId}`,
          error: sanitizeError(error),
        });
      }
    }

    // The provisioner has already walked the parent's ancestors and granted READ on the new
    // root's direct parent, so when a `precomputedRootPath` is provided we can skip the second
    // walk entirely.
    const rootPath =
      precomputedRootPath ?? (await this.resolveScopePathCommand.execute(rootScope, userId));
    this.logger.log(`Resolved root path: ${smearPath(rootPath)}`);

    return { rootScopeId, serviceUserId: userId, rootPath, isInitialSync };
  }

  private async resolveRootScopeId(
    siteConfig: SiteConfig,
    siteName: Smeared,
  ): Promise<{ rootScopeId: string; precomputedRootPath: Smeared | undefined }> {
    if (isFixedScope(siteConfig.scopeId)) {
      return { rootScopeId: siteConfig.scopeId.scopeId, precomputedRootPath: undefined };
    }

    const configuredParentId = siteConfig.scopeId.parentScopeId;
    const logPrefix = `[Site: ${siteConfig.siteId}] [Parent: ${configuredParentId}]`;

    const found = await this.findRootScopeQuery.execute(siteConfig, { siteName });
    if (found) {
      if (found.parentId !== configuredParentId) {
        this.logger.log(
          `${logPrefix} Moving root scope ${found.id} from parent ` +
            `${found.parentId ?? 'null'} to configured parent ${configuredParentId}`,
        );
        await this.uniqueScopesService.updateScopeParent(found.id, configuredParentId);
      }
      return { rootScopeId: found.id, precomputedRootPath: undefined };
    }

    const created = await this.createRootScopeCommand.execute(siteConfig, siteName);
    return { rootScopeId: created.rootScopeId, precomputedRootPath: created.rootPath };
  }

  // A null externalId means the scope is freshly created and unclaimed — any site is allowed to
  // claim it. Once claimed, the shared `isOwnedBySite` predicate decides ownership (legacy or
  // new format both accepted).
  private isValidScopeOwnership(rootScope: Scope, siteId: Smeared): boolean {
    return rootScope.externalId === null || isOwnedBySite(rootScope, siteId.value);
  }
}
