import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { buildScopePathFromItem } from '../utils/sharepoint.util';

@Injectable()
export class ScopeManagementService {
  private readonly logger = new Logger(ScopeManagementService.name);

  public constructor(
    private readonly configService: ConfigService,
    private readonly uniqueScopesService: UniqueScopesService,
  ) {}

  private buildItemIdToScopePathMap(
    items: SharepointContentItem[],
    rootScopeName: string,
  ): Map<string, string> {
    const itemIdToScopePathMap = new Map<string, string>();

    for (const item of items) {
      try {
        const scopePath = buildScopePathFromItem(item, rootScopeName);
        itemIdToScopePathMap.set(item.item.id, scopePath);
      } catch (error) {
        this.logger.warn(
          `Failed to build scope path for item: ${item.item.id} ${item.item.webUrl} ${error}`,
        );
      }
    }

    return itemIdToScopePathMap;
  }

  /**
   * Extracts all unique parent directory paths from a list of path strings.
   * @param paths An array of raw path strings.
   * @returns A deduplicated array of all parent paths (e.g., "/a", "/a/b").
   */
  public extractAllParentPaths(paths: string[]): string[] {
    const allGeneratedPaths = paths.flatMap((path) => this.generatePathsFromSingleString(path));

    const result = Array.from(new Set(allGeneratedPaths));

    if (result.length === 0) {
      this.logger.warn('extractAllParentPaths returned no paths');
    }

    return result;
  }

  private generatePathsFromSingleString(path: string): string[] {
    const trimmedPath = path.trim();

    if (!trimmedPath) {
      this.logger.warn('Skipping empty path');
      return [];
    }

    const segments = trimmedPath.split('/').filter((segment) => segment.length > 0);

    if (segments.length === 0) {
      this.logger.warn(`Path has no valid segments: ${path}`);
      return [];
    }

    return segments.map((_, index) => {
      const parentSegments = segments.slice(0, index + 1);
      return `/${parentSegments.join('/')}`;
    });
  }

  public async batchCreateScopes(items: SharepointContentItem[]): Promise<Scope[]> {
    const siteId = items[0]?.siteId || 'unknown siteId';
    const rootScopeName = this.configService.get('unique.rootScopeName', {
      infer: true,
    });
    assert(rootScopeName, 'rootScopeName must be configured');

    const itemIdToScopePathMap = this.buildItemIdToScopePathMap(items, rootScopeName);
    const uniqueFolderPaths = new Set(itemIdToScopePathMap.values());

    if (uniqueFolderPaths.size === 0) {
      this.logger.log(`[SiteId: ${siteId}] No folder paths to create scopes for`);
      return [];
    }

    // Extract all parent paths from the folder paths
    const allPathsWithParents = this.extractAllParentPaths(Array.from(uniqueFolderPaths));

    const scopes = await this.uniqueScopesService.createScopesBasedOnPaths(allPathsWithParents, {
      includePermissions: true,
    });

    this.logger.log(`[SiteId: ${siteId}] Created ${scopes.length} scopes`);

    return scopes;
  }

  public buildItemIdToScopeIdMap(
    items: SharepointContentItem[],
    scopes: Scope[],
  ): Map<string, string> {
    const itemIdToScopeIdMap = new Map<string, string>();
    const rootScopeName = this.configService.get('unique.rootScopeName', {
      infer: true,
    });

    if (!rootScopeName || scopes.length === 0) {
      return itemIdToScopeIdMap;
    }

    // Build path -> scopeId map from scopes
    const scopePathToIdMap: Record<string, string> = {};
    for (const scope of scopes) {
      scopePathToIdMap[scope.name] = scope.id;
    }

    // Build item -> path map
    const itemIdToScopePathMap = this.buildItemIdToScopePathMap(items, rootScopeName);

    for (const [itemId, scopePath] of itemIdToScopePathMap) {
      const decodedPath = decodeURIComponent(scopePath);
      const scopeId = scopePathToIdMap[decodedPath];
      if (scopeId) {
        itemIdToScopeIdMap.set(itemId, scopeId);
      } else {
        this.logger.warn(`Scope not found in cache for path: ${decodedPath}`);
      }
    }
    return itemIdToScopeIdMap;
  }
}
