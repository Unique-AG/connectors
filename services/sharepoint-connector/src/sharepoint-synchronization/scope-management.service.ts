import assert from 'node:assert';
import { randomUUID } from 'node:crypto';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { isNonNullish, isNullish, prop, pullObject } from 'remeda';
import { Config } from '../config';
import { getInheritanceSettings } from '../config/sharepoint.schema';
import { IngestionMode } from '../constants/ingestion.constants';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { Scope, ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import {
  EXTERNAL_ID_PREFIX,
  redact,
  shouldConcealLogs,
  smear,
  smearExternalId,
  smearPath,
} from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';
import { isAncestorOfRootPath } from '../utils/paths.util';
import { getUniqueParentPathFromItem, getUniquePathFromItem } from '../utils/sharepoint.util';
import type { SharepointSyncContext } from './sharepoint-sync-context.interface';

export interface RootScopeInfo {
  serviceUserId: string;
  rootPath: string;
}

@Injectable()
export class ScopeManagementService {
  private readonly logger = new Logger(ScopeManagementService.name);
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly uniqueUsersService: UniqueUsersService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  public async initializeRootScope(
    rootScopeId: string,
    siteId: string,
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
    if (!isValid) {
      const expectedExternalId = `${EXTERNAL_ID_PREFIX}site:${siteId}`;
      throw new Error(
        `Root scope ${rootScopeId} is owned by a different site. Expected externalId "${
          this.shouldConcealLogs ? smearExternalId(expectedExternalId) : expectedExternalId
        }" but got "${
          this.shouldConcealLogs ? smearExternalId(rootScope.externalId) : rootScope.externalId
        }". This scope cannot be synced by this site.`,
      );
    }

    if (!rootScope.externalId) {
      const externalId = `${EXTERNAL_ID_PREFIX}site:${siteId}`;
      try {
        const updatedScope = await this.uniqueScopesService.updateScopeExternalId(
          rootScopeId,
          externalId,
        );
        rootScope.externalId = updatedScope.externalId;
        this.logger.debug(
          `${logPrefix} Claimed root scope ${rootScopeId} with externalId: ${
            this.shouldConcealLogs ? smearExternalId(externalId) : externalId
          }`,
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
      // Grant READ and WRITE permissions first before accessing the parent scope. Otherwise we will
      // not get it via `getScopeById` call. And without WRITE permission we will not be able to
      // create the scope accesses for the parent scope.
      await this.uniqueScopesService.createScopeAccesses(currentScope.parentId, [
        { type: 'READ', entityId: userId, entityType: 'USER' },
        { type: 'WRITE', entityId: userId, entityType: 'USER' },
      ]);

      const parent = await this.uniqueScopesService.getScopeById(currentScope.parentId);

      assert.ok(
        parent,
        `Parent scope ${currentScope.parentId} not found for scope ${currentScope.id}`,
      );

      pathSegments.unshift(parent.name);
      currentScope = parent;
    }

    const rootPath = `/${pathSegments.join('/')}`;
    this.logger.log(`Resolved root path: ${this.shouldConcealLogs ? redact(rootPath) : rootPath}`);

    return { serviceUserId: userId, rootPath };
  }

  public async deleteRootScopeRecursively(scopeId: string): Promise<void> {
    const logPrefix = `[RootScopeId: ${scopeId}]`;
    this.logger.log(`${logPrefix} Deleting root scope recursively`);

    try {
      const result = await this.uniqueScopesService.deleteScopeRecursively(scopeId);

      if (result.successFolders.length > 0) {
        this.logger.log(
          `${logPrefix} Successfully deleted ${result.successFolders.length} folders`,
        );
      }

      if (result.failedFolders.length > 0) {
        this.logger.warn({
          msg: `${logPrefix} Failed to delete ${result.failedFolders.length} folders`,
          failedFolders: result.failedFolders.map((f) => ({
            id: f.id,
            name: f.name,
            path: this.shouldConcealLogs ? redact(f.path) : f.path,
            reason: f.failReason,
          })),
        });
      }
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to delete root scope recursively`,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  private isValidScopeOwnership(rootScope: Scope, siteId: string): boolean {
    if (!rootScope.externalId) {
      return true;
    }

    const expectedExternalId = `${EXTERNAL_ID_PREFIX}site:${siteId}`;
    return rootScope.externalId === expectedExternalId;
  }

  private buildItemIdToScopePathMap(
    items: SharepointContentItem[],
    rootPath: string,
  ): Map<string, string> {
    const itemIdToScopePathMap = new Map<string, string>();

    for (const item of items) {
      const scopePath = getUniqueParentPathFromItem(item, rootPath);
      itemIdToScopePathMap.set(item.item.id, scopePath);
    }

    return itemIdToScopePathMap;
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
      this.logger.warn(
        `Path has no valid segments: ${this.shouldConcealLogs ? redact(path) : path}`,
      );
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
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(context.siteConfig.siteId) : context.siteConfig.siteId}]`;

    const itemIdToScopePathMap = this.buildItemIdToScopePathMap(items, context.rootPath);
    const uniqueFolderPaths = new Set(itemIdToScopePathMap.values());

    if (uniqueFolderPaths.size === 0) {
      this.logger.log(`${logPrefix} No folder paths to create scopes for`);
      return [];
    }

    // Extract all parent paths from the folder paths
    const allPathsWithParents = this.extractAllParentPaths(Array.from(uniqueFolderPaths));

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

  /* Sets the external id on newly created scopes.
   * This is necessary after creating a new scope to make the scope non editable for other users, essentially marking
   * the scope as externally created.
   */
  private async updateNewlyCreatedScopesWithExternalId(
    scopes: Scope[],
    paths: string[],
    directories: SharepointDirectoryItem[],
    context: SharepointSyncContext,
  ): Promise<void> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(context.siteConfig.siteId) : context.siteConfig.siteId}]`;
    const pathToExternalIdMap = this.buildPathToExternalIdMap(directories, context.rootPath);
    // Site pages is a special collection we fetch for ASPX pages, but has no folders.
    pathToExternalIdMap[`${context.rootPath}/SitePages`] =
      `${EXTERNAL_ID_PREFIX}${context.siteConfig.siteId}/sitePages`;

    for (const [index, scope] of scopes.entries()) {
      if (isNonNullish(scope.externalId)) {
        continue;
      }

      const path = paths[index] ?? '';

      // Skip setting external ID for scopes that are ancestors of the root ingestion folder
      if (isAncestorOfRootPath(path, context.rootPath)) {
        this.logger.debug(
          `${logPrefix} Skipping externalId update for scope ${scope.id} because it is ancestor ` +
            `to the ingestion root scope`,
        );
        continue;
      }

      /* We have a couple of known directories in sharepoint for which it's more complex to get the id: root scope,
       * sites, <site-name>, Shared Documents. For these we're setting the external id to be the scope name.
       */
      let externalId = pathToExternalIdMap[path];
      if (isNullish(externalId)) {
        this.logger.warn(
          `${logPrefix} No external ID found for path ` +
            `${this.shouldConcealLogs ? smearPath(path) : path}`,
        );
        externalId = `${EXTERNAL_ID_PREFIX}unknown:${context.siteConfig.siteId}/${scope.name}-${randomUUID()}`;
      }

      try {
        const updatedScope = await this.uniqueScopesService.updateScopeExternalId(
          scope.id,
          externalId,
        );
        scope.externalId = updatedScope.externalId;
        this.logger.debug(
          `Updated scope ${scope.id} with externalId: ${
            this.shouldConcealLogs ? smearExternalId(externalId) : externalId
          }`,
        );
      } catch (error) {
        this.logger.warn({
          msg: `Failed to update externalId for scope ${scope.id}`,
          error: sanitizeError(error),
        });
      }
    }
  }

  private buildPathToExternalIdMap(
    directories: SharepointDirectoryItem[],
    rootPath: string,
  ): Record<string, string> {
    const pathToExternalIdMap: Record<string, string> = {};

    for (const directory of directories) {
      const path = getUniquePathFromItem(directory, rootPath);
      if (isAncestorOfRootPath(path, rootPath) || path === rootPath) {
        continue;
      }

      const pathWithoutRoot = path.substring(rootPath.length);
      const segments = pathWithoutRoot.split('/').filter(Boolean);
      pathToExternalIdMap[path] =
        `${EXTERNAL_ID_PREFIX}folder:${directory.siteId}/${directory.item.id}`;
      // siteName is now stripped, so first segment is already the drive
      pathToExternalIdMap[`${rootPath}/${segments[0]}`] ??=
        `${EXTERNAL_ID_PREFIX}drive:${directory.siteId}/${directory.driveId}`;
    }

    return pathToExternalIdMap;
  }

  public buildItemIdToScopeIdMap(
    items: SharepointContentItem[],
    scopes: ScopeWithPath[],
    context: SharepointSyncContext,
  ): Map<string, string> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(context.siteConfig.siteId) : context.siteConfig.siteId}]`;
    const itemIdToScopeIdMap = new Map<string, string>();

    if (scopes.length === 0) {
      return itemIdToScopeIdMap;
    }

    // Build path -> scopeId map from scopes
    const scopePathToIdMap = pullObject(scopes, prop('path'), prop('id'));

    this.logger.debug(
      `${logPrefix} Built scopePathToIdMap with ${Object.keys(scopePathToIdMap).length} entries`,
    );

    // Build item -> path map
    const itemIdToScopePathMap = this.buildItemIdToScopePathMap(items, context.rootPath);

    this.logger.debug(
      `${logPrefix} Built itemIdToScopePathMap with ${itemIdToScopePathMap.size} entries`,
    );

    for (const [itemId, scopePath] of itemIdToScopePathMap) {
      const scopeId = scopePathToIdMap[scopePath];
      if (scopeId) {
        itemIdToScopeIdMap.set(itemId, scopeId);
      } else {
        this.logger.warn(
          `${logPrefix} Scope not found in cache for path: ${this.shouldConcealLogs ? redact(scopePath) : scopePath}`,
        );
      }
    }

    this.logger.debug(
      `${logPrefix} Built itemIdToScopeIdMap with ${itemIdToScopeIdMap.size} entries for ${items.length} items`,
    );

    return itemIdToScopeIdMap;
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

    const scopePath = getUniqueParentPathFromItem(item, context.rootPath);

    // Find scope with this path.
    const scope = scopes.find((scope) => scope.path === scopePath);
    if (!scope?.id) {
      this.logger.warn(
        `Scope not found for path: ${this.shouldConcealLogs ? redact(scopePath) : scopePath}`,
      );
      return undefined;
    }
    return scope.id;
  }
}
