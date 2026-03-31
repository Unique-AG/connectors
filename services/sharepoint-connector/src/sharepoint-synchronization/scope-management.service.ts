import assert from 'node:assert';
import { randomUUID } from 'node:crypto';
import { Injectable, Logger } from '@nestjs/common';
import { isNonNullish, isNullish, sortBy, unique } from 'remeda';
import { getInheritanceSettings } from '../config/sharepoint.schema';
import { IngestionMode } from '../constants/ingestion.constants';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { Scope, ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import { EXTERNAL_ID_PREFIX, PENDING_DELETE_PREFIX } from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';
import { isAncestorOfRootPath } from '../utils/paths.util';
import { getUniqueParentPathFromItem, getUniquePathFromItem } from '../utils/sharepoint.util';
import { createSmeared, Smeared, smearPath } from '../utils/smeared';
import { RootScopeMigrationService } from './root-scope-migration.service';
import type { SharepointSyncContext } from './sharepoint-sync-context.interface';

const buildSiteExternalId = (siteId: Smeared) =>
  createSmeared(`${EXTERNAL_ID_PREFIX}site:${siteId.value}`);

export interface RootScopeInfo {
  serviceUserId: string;
  rootPath: Smeared;
  isInitialSync: boolean;
}

@Injectable()
export class ScopeManagementService {
  private readonly logger = new Logger(ScopeManagementService.name);

  public constructor(
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly uniqueUsersService: UniqueUsersService,
    private readonly rootScopeMigrationService: RootScopeMigrationService,
  ) {}

  public async initializeRootScope(
    rootScopeId: string,
    siteId: Smeared,
    ingestionMode: IngestionMode,
  ): Promise<RootScopeInfo> {
    const userId = await this.uniqueUsersService.getCurrentUserId();
    assert.ok(userId, 'User ID must be available');
    const logPrefix = `[RootScopeId: ${rootScopeId}]`;

    this.logger.log(`${logPrefix} Initializing root scope (Mode: ${ingestionMode})`);

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

    const isInitialSync = !rootScope.externalId;

    if (isInitialSync) {
      const migrationResult = await this.rootScopeMigrationService.migrateIfNeeded(
        rootScopeId,
        siteId,
      );
      if (migrationResult.status === 'migration_failed') {
        throw new Error(`Root scope migration failed: ${migrationResult.error}`);
      }

      const externalId = buildSiteExternalId(siteId);
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

    const pathSegments = [rootScope.name];
    let currentScope: Scope = rootScope;

    while (currentScope.parentId) {
      // Grant READ permission first before accessing the parent scope. Otherwise we will not get it
      // via `getScopeById` call.
      await this.uniqueScopesService.createScopeAccesses(currentScope.parentId, [
        { type: 'READ', entityId: userId, entityType: 'USER' },
      ]);

      const parent = await this.uniqueScopesService.getScopeById(currentScope.parentId);

      assert.ok(
        parent,
        `Parent scope ${currentScope.parentId} not found for scope ${currentScope.id}`,
      );

      pathSegments.unshift(parent.name);
      currentScope = parent;
    }

    const rootPath = createSmeared(`/${pathSegments.join('/')}`);
    this.logger.log(`Resolved root path: ${smearPath(rootPath)}`);

    return { serviceUserId: userId, rootPath, isInitialSync };
  }

  public async resetRootScope(scopeId: string): Promise<void> {
    const logPrefix = `[RootScopeId: ${scopeId}]`;
    this.logger.log(`${logPrefix} Resetting root scope (deleting children, clearing externalId)`);

    try {
      const children = await this.uniqueScopesService.listChildrenScopes(scopeId);
      this.logger.log(`${logPrefix} Found ${children.length} child scopes to delete`);

      // Children are deleted sequentially and the method throws on the first failure.
      // This is intentional: on transient errors the operation can be safely resumed
      // because already-deleted children won't be returned by listChildrenScopes.
      for (const child of children) {
        const result = await this.uniqueScopesService.deleteScope(child.id, { recursive: true });

        if (result.failedFolders.length > 0) {
          this.logger.warn({
            msg: `${logPrefix} Partial deletion failure for child scope ${child.id}`,
            failedFolders: result.failedFolders.map((f) => ({
              id: f.id,
              name: f.name,
              path: createSmeared(f.path),
              reason: f.failReason,
            })),
          });
        }

        assert.strictEqual(
          result.failedFolders.length,
          0,
          `Failed to fully delete child scope ${child.id}: ` +
            `${result.failedFolders.length} folders could not be removed`,
        );
      }

      await this.uniqueScopesService.updateScopeExternalId(scopeId, null);
      this.logger.log(`${logPrefix} Cleared externalId on root scope`);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to reset root scope`,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  public async deleteOrphanedScopes(siteId: Smeared): Promise<void> {
    const logPrefix = `[Site: ${siteId}]`;

    // Note: When subsites are enabled, we do not need to iterate over all discovered subsite IDs.
    // This is because `markConflictingScope` (which marks scopes for deletion) constructs the
    // pending-delete prefix using the root site's ID for all items, including those from subsites.
    // Therefore, querying by the root site's ID prefix is sufficient to find all orphaned scopes
    // for the entire site tree.
    let orphanedScopes: Scope[];
    try {
      orphanedScopes = await this.uniqueScopesService.listScopesByExternalIdPrefix(
        siteId.transform((value) => `${PENDING_DELETE_PREFIX}${value}/`),
      );
    } catch (error) {
      this.logger.warn({
        msg: `${logPrefix} Failed to query orphaned scopes, skipping cleanup`,
        error: sanitizeError(error),
      });
      return;
    }

    if (orphanedScopes.length === 0) {
      return;
    }

    // We sort the orphans by depth to delete the deepest scopes first to avoid deleting scopes that
    // have children. This way we can delete without recursive to be sure we're not accidentally
    // deleting some content.

    const orphanById = new Map(orphanedScopes.map((s) => [s.id, s]));
    const depthById = new Map<string, number>();

    const setOrphanDepth = (scope: Scope): number => {
      const cached = depthById.get(scope.id);
      if (isNonNullish(cached)) {
        return cached;
      }

      let depth = 0;
      const parent = scope.parentId ? orphanById.get(scope.parentId) : undefined;
      if (parent) {
        depth = 1 + setOrphanDepth(parent);
      }
      depthById.set(scope.id, depth);
      return depth;
    };

    for (const scope of orphanedScopes) {
      setOrphanDepth(scope);
    }

    const sortedOrphans = sortBy(orphanedScopes, [(scope) => depthById.get(scope.id) ?? 0, 'desc']);

    this.logger.log(
      `${logPrefix} Deleting ${orphanedScopes.length} orphaned scopes marked with pending-delete prefix`,
    );

    for (const scope of sortedOrphans) {
      try {
        await this.uniqueScopesService.deleteScope(scope.id);
        this.logger.debug(`${logPrefix} Deleted orphaned scope ${scope.id}`);
      } catch (error) {
        this.logger.warn({
          msg: `${logPrefix} Failed to delete orphaned scope ${scope.id}`,
          error: sanitizeError(error),
        });
      }
    }
  }

  private isValidScopeOwnership(rootScope: Scope, siteId: Smeared): boolean {
    if (!rootScope.externalId) {
      return true;
    }

    const expectedExternalId = buildSiteExternalId(siteId);
    return rootScope.externalId === expectedExternalId.value;
  }

  /**
   * Extracts all unique parent directory paths from a list of path strings.
   * @param paths An array of raw path strings.
   * @returns A deduplicated array of all parent paths (e.g., "/a", "/a/b").
   */
  public extractAllParentPaths(paths: string[]): string[] {
    const allGeneratedPaths = paths.flatMap((path) => this.generateAllSubpathsFromPath(path));

    const result = Array.from(new Set(allGeneratedPaths));

    if (result.length === 0) {
      this.logger.warn('extractAllParentPaths returned no paths');
    }

    return result;
  }

  private generateAllSubpathsFromPath(path: string): string[] {
    const trimmedPath = path.trim();

    if (!trimmedPath) {
      this.logger.warn('Skipping empty path');
      return [];
    }

    const segments = trimmedPath.split('/').filter((segment) => segment.length > 0);

    if (segments.length === 0) {
      this.logger.warn(`Path has no valid segments: ${createSmeared(path)}`);
      return [];
    }

    return segments.map((_, index) => {
      const parentSegments = segments.slice(0, index + 1);
      return `/${parentSegments.join('/')}`;
    });
  }

  public async batchCreateScopes(
    items: SharepointContentItem[],
    directories: SharepointDirectoryItem[],
    context: SharepointSyncContext,
  ): Promise<ScopeWithPath[]> {
    const logPrefix = `[Site: ${context.siteConfig.siteId}]`;

    const uniqueFolderPaths = items.map(
      (item) => getUniqueParentPathFromItem(item, context.rootPath, context.siteName).value,
    );

    if (uniqueFolderPaths.length === 0) {
      this.logger.log(`${logPrefix} No folder paths to create scopes for`);
      return [];
    }

    // Extract all parent paths from the folder paths
    const allPathsWithParents = this.extractAllParentPaths(unique(uniqueFolderPaths));

    this.logger.debug(`${logPrefix} Sending ${allPathsWithParents.length} paths to API`);

    const { inheritScopes } = getInheritanceSettings(context.siteConfig);
    const scopes = await this.uniqueScopesService.createScopesBasedOnPaths(allPathsWithParents, {
      includePermissions: true,
      inheritAccess: inheritScopes,
    });
    this.logger.log(`${logPrefix} Created ${scopes.length} scopes`);

    // Update newly created scopes with externalId
    await this.updateNewlyCreatedScopesWithExternalId(
      scopes,
      allPathsWithParents,
      items,
      directories,
      context,
    );

    // Add the full path to each scope object
    // The API returns scopes in the same order as the input paths
    const scopesWithPaths: ScopeWithPath[] = scopes.map((scope, index) => ({
      ...scope,
      path: allPathsWithParents[index] || assert.fail(`No matching path for scope ${scope.id}`),
    }));

    this.logger.log(`${logPrefix} Created ${scopes.length} scopes with paths`);
    return scopesWithPaths;
  }

  // Sets the externalId on new scopes so they're non-editable for other users. Makes the scope
  // externally managed.
  private async updateNewlyCreatedScopesWithExternalId(
    scopes: Scope[],
    paths: string[],
    items: SharepointContentItem[],
    directories: SharepointDirectoryItem[],
    context: SharepointSyncContext,
  ): Promise<void> {
    const logPrefix = `[Site: ${context.siteConfig.siteId}]`;
    const pathToExternalIdMap = this.buildPathToExternalIdMap(items, directories, context);

    for (const [index, scope] of scopes.entries()) {
      if (isNonNullish(scope.externalId)) {
        continue;
      }

      const path = paths[index] ?? '';

      // Skip setting external ID for scopes that are ancestors of the root ingestion folder
      if (isAncestorOfRootPath(path, context.rootPath.value)) {
        this.logger.debug(
          `${logPrefix} Skipping externalId update for scope ${scope.id} because it is ancestor ` +
            `to the ingestion root scope`,
        );
        continue;
      }

      let externalId = pathToExternalIdMap[path]
        ? createSmeared(pathToExternalIdMap[path])
        : undefined;

      if (isNullish(externalId)) {
        this.logger.warn(`${logPrefix} No external ID found for path ${createSmeared(path)}`);
        externalId = createSmeared(
          `${EXTERNAL_ID_PREFIX}unknown:${context.siteConfig.siteId.value}::${path}-${randomUUID()}`,
        );
      }

      if (!context.isInitialSync) {
        await this.markConflictingScope(scope.id, externalId, context.siteConfig.siteId, logPrefix);
      }

      try {
        const updatedScope = await this.uniqueScopesService.updateScopeExternalId(
          scope.id,
          externalId,
        );
        scope.externalId = updatedScope.externalId;
        this.logger.debug(`Updated scope ${scope.id} with externalId: ${externalId}`);
      } catch (error) {
        this.logger.warn({
          msg: `Failed to update externalId for scope ${scope.id}`,
          error: sanitizeError(error),
        });
      }
    }
  }

  // When folder was moved in SharePoint, we will recreate it at a new location because we create
  // scopes by path and not by id. Therefore if we find a scope with the same externalId, we mark it
  // for deletion. It will happen after content sync, because we have to move files from old scopes
  // to new ones.
  private async markConflictingScope(
    newScopeId: string,
    externalId: Smeared,
    siteId: Smeared,
    logPrefix: string,
  ): Promise<void> {
    try {
      const existingScope = await this.uniqueScopesService.getScopeByExternalId(externalId.value);

      if (!existingScope || existingScope.id === newScopeId) {
        return;
      }

      const pendingDeleteExternalId = externalId.transform((value) =>
        value.replace(EXTERNAL_ID_PREFIX, `${PENDING_DELETE_PREFIX}${siteId.value}/`),
      );
      this.logger.log(
        `${logPrefix} Marking conflicting scope ${existingScope.id} with pending-delete prefix`,
      );
      await this.uniqueScopesService.updateScopeExternalId(
        existingScope.id,
        pendingDeleteExternalId,
      );
    } catch (error) {
      this.logger.warn({
        msg: `${logPrefix} Failed to mark conflicting scope for externalId ${externalId}`,
        error: sanitizeError(error),
      });
    }
  }

  private buildPathToExternalIdMap(
    items: SharepointContentItem[],
    directories: SharepointDirectoryItem[],
    context: SharepointSyncContext,
  ): Record<string, string> {
    const { rootPath, siteName, siteConfig, discoveredSubsites } = context;
    const pathToExternalIdMap: Record<string, string> = {};

    const siteIdToPrefix = new Map<string, string>();
    for (const subsite of discoveredSubsites) {
      siteIdToPrefix.set(subsite.siteId.value, subsite.relativePath.value);
      pathToExternalIdMap[`${rootPath.value}/${subsite.relativePath.value}`] ??=
        `${EXTERNAL_ID_PREFIX}subsite:${subsite.siteId.value}`;
      // Site pages is a special collection we fetch for ASPX pages, but has no folders.
      pathToExternalIdMap[`${rootPath.value}/${subsite.relativePath.value}/SitePages`] =
        `${EXTERNAL_ID_PREFIX}${subsite.siteId.value}/sitePages`;
    }

    // Site pages is a special collection we fetch for ASPX pages, but has no folders.
    pathToExternalIdMap[`${rootPath.value}/SitePages`] =
      `${EXTERNAL_ID_PREFIX}${siteConfig.siteId.value}/sitePages`;

    const registeredDrives = new Set<string>();

    for (const directory of directories) {
      const path = getUniquePathFromItem(directory, rootPath, siteName);
      if (isAncestorOfRootPath(path.value, rootPath.value) || path.value === rootPath.value) {
        continue;
      }

      pathToExternalIdMap[path.value] ??=
        `${EXTERNAL_ID_PREFIX}folder:${directory.siteId.value}/${directory.item.id}`;

      const sitePrefix = siteIdToPrefix.get(directory.siteId.value);
      const siteScopePath = sitePrefix ? `${rootPath.value}/${sitePrefix}` : rootPath.value;
      const driveRelative = path.value.substring(siteScopePath.length);
      const segments = driveRelative.split('/').filter(Boolean);
      // Segments can be empty when a directory resolves to exactly the site scope path.
      if (segments[0]) {
        registeredDrives.add(`${directory.siteId.value}/${directory.driveId}`);
        pathToExternalIdMap[`${siteScopePath}/${segments[0]}`] ??=
          `${EXTERNAL_ID_PREFIX}drive:${directory.siteId.value}/${directory.driveId}`;
      }
    }

    // Register drive-level mappings from items for drives that had no subdirectories.
    // Without this, drives containing only root-level files would get spc:unknown: external IDs.
    for (const item of items) {
      if (item.itemType !== 'driveItem') {
        continue;
      }

      const driveKey = `${item.siteId.value}/${item.driveId}`;
      if (registeredDrives.has(driveKey)) {
        continue;
      }
      registeredDrives.add(driveKey);

      // Resolve the item's parent path (e.g. "/Company/Root/SubA/Shared Documents/FolderA")
      const parentPath = getUniqueParentPathFromItem(item, rootPath, siteName);

      // Determine the scope path for the site or subsite this item belongs to
      // (e.g. "/Company/Root" for main site items, "/Company/Root/SubA" for subsite items)
      const sitePrefix = siteIdToPrefix.get(item.siteId.value);
      const siteScopePath = sitePrefix ? `${rootPath.value}/${sitePrefix}` : rootPath.value;

      // Extract the path relative to the site scope, then take the first segment — that's the
      // drive/library name (e.g. "/Shared Documents/FolderA" → "Shared Documents")
      const driveRelative = parentPath.value.substring(siteScopePath.length);
      const segments = driveRelative.split('/').filter(Boolean);
      if (segments[0]) {
        pathToExternalIdMap[`${siteScopePath}/${segments[0]}`] ??=
          `${EXTERNAL_ID_PREFIX}drive:${item.siteId.value}/${item.driveId}`;
      }
    }

    return pathToExternalIdMap;
  }

  /**
   * Determines the appropriate scope ID for a SharePoint item based on ingestion mode
   */
  public determineScopeForItem(
    item: SharepointContentItem,
    scopes: ScopeWithPath[] | null,
    context: SharepointSyncContext,
  ): string | undefined {
    if (!scopes || scopes.length === 0) {
      // Flat mode - return the configured scope ID
      return context.siteConfig.scopeId;
    }

    const scopePath = getUniqueParentPathFromItem(item, context.rootPath, context.siteName);

    // Find scope with this path.
    const scope = scopes.find((scope) => scope.path === scopePath.value);
    if (!scope?.id) {
      this.logger.warn(`Scope not found for path: ${scopePath}`);
      return undefined;
    }
    return scope.id;
  }
}
