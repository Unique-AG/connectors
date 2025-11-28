import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { prop, pullObject } from 'remeda';
import { IngestionMode } from '../constants/ingestion.constants';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { Scope, ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import { redact, shouldConcealLogs, smear } from '../utils/logging.util';
import { getUniqueParentPathFromItem } from '../utils/sharepoint.util';
import type { BaseSyncContext, SharepointSyncContext } from './types';

@Injectable()
export class ScopeManagementService {
  private readonly logger = new Logger(ScopeManagementService.name);
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly uniqueUsersService: UniqueUsersService,
    private readonly configService: ConfigService,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  public async initializeRootScope(
    rootScopeId: string,
    ingestionMode: IngestionMode,
  ): Promise<BaseSyncContext> {
    const userId = await this.uniqueUsersService.getCurrentUserId();
    assert.ok(userId, 'User ID must be available');

    this.logger.log(`Initializing root scope ${rootScopeId} (Mode: ${ingestionMode})`);

    await this.uniqueScopesService.createScopeAccesses(rootScopeId, [
      { type: 'MANAGE', entityId: userId, entityType: 'USER' },
      { type: 'READ', entityId: userId, entityType: 'USER' },
      { type: 'WRITE', entityId: userId, entityType: 'USER' },
    ]);

    const rootScope = await this.uniqueScopesService.getScopeById(rootScopeId);
    assert.ok(rootScope, `Root scope with ID ${rootScopeId} not found`);

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

    const rootPath = `/${pathSegments.join('/')}`;
    this.logger.log(`Resolved root path: ${this.shouldConcealLogs ? redact(rootPath) : rootPath}`);

    return { serviceUserId: userId, rootScopeId: rootScopeId, rootPath };
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
    context: SharepointSyncContext,
  ): Promise<ScopeWithPath[]> {
    const logPrefix = `[SiteId: ${this.shouldConcealLogs ? smear(context.siteId) : context.siteId}]`;

    const itemIdToScopePathMap = this.buildItemIdToScopePathMap(items, context.rootPath);
    const uniqueFolderPaths = new Set(itemIdToScopePathMap.values());

    if (uniqueFolderPaths.size === 0) {
      this.logger.log(`${logPrefix} No folder paths to create scopes for`);
      return [];
    }

    // Extract all parent paths from the folder paths
    const allPathsWithParents = this.extractAllParentPaths(Array.from(uniqueFolderPaths));

    this.logger.debug(`${logPrefix} Sending ${allPathsWithParents.length} paths to API`);

    const scopes = await this.uniqueScopesService.createScopesBasedOnPaths(allPathsWithParents, {
      includePermissions: true,
    });
    this.logger.log(`${logPrefix} Created ${scopes.length} scopes`);

    // Add the full path to each scope object
    // The API returns scopes in the same order as the input paths
    const scopesWithPaths: ScopeWithPath[] = scopes.map((scope, index) => ({
      ...scope,
      path: allPathsWithParents[index] || assert.fail(`No matching path for scope ${scope.id}`),
    }));

    this.logger.log(`${logPrefix} Created ${scopes.length} scopes with paths`);
    return scopesWithPaths;
  }

  public buildItemIdToScopeIdMap(
    items: SharepointContentItem[],
    scopes: ScopeWithPath[],
    context: SharepointSyncContext,
  ): Map<string, string> {
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(context.siteId) : context.siteId}]`;
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
      return context.rootScopeId;
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
