import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { buildScopePathFromItem } from '../utils/sharepoint.util';

@Injectable()
export class ScopeManagementService {
  private readonly logger = new Logger(ScopeManagementService.name);

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly uniqueScopesService: UniqueScopesService,
  ) {}

  private buildItemIdToScopePathMap(
    items: SharepointContentItem[],
    rootScopeName: string,
  ): Map<string, string> {
    const itemIdToScopePathMap = new Map<string, string>();

    for (const item of items) {
      const scopePath = buildScopePathFromItem(item, rootScopeName);
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
    const logPrefix = `[SiteId: ${items[0]?.siteId || 'unknown siteId'}]`;
    const rootScopeName = this.configService.get('unique.rootScopeName', {
      infer: true,
    });
    assert(rootScopeName, 'rootScopeName must be configured');

    const itemIdToScopePathMap = this.buildItemIdToScopePathMap(items, rootScopeName);
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
    const scopesWithPaths = scopes.map((scope, index) => {
      const inputPath = allPathsWithParents[index];
      const normalizedPath = inputPath?.startsWith('/') ? inputPath.slice(1) : inputPath;

      return {
        ...scope,
        path: normalizedPath,
      };
    });

    this.logger.log(`${logPrefix} Created ${scopes.length} scopes with paths`);
    return scopesWithPaths;
  }

  public buildItemIdToScopeIdMap(
    items: SharepointContentItem[],
    scopes: Scope[],
  ): Map<string, string> {
    const logPrefix = items[0]?.siteId || '';
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
      if ('path' in scope && typeof scope.path === 'string') {
        scopePathToIdMap[scope.path] = scope.id;
      } else {
        this.logger.warn(
          `Scope missing path property: ${JSON.stringify({ id: scope.id, name: scope.name })}`,
        );
      }
    }

    this.logger.debug(
      `${logPrefix} Built scopePathToIdMap with ${Object.keys(scopePathToIdMap).length} entries`,
    );

    // Build item -> path map
    const itemIdToScopePathMap = this.buildItemIdToScopePathMap(items, rootScopeName);

    this.logger.debug(`${logPrefix} Built itemIdToScopePathMap with ${itemIdToScopePathMap.size} entries`);

    for (const [itemId, scopePath] of itemIdToScopePathMap) {
      const scopeId = scopePathToIdMap[scopePath];
      if (scopeId) {
        itemIdToScopeIdMap.set(itemId, scopeId);
      } else {
        this.logger.warn(`${logPrefix} Scope not found in cache for path: ${scopePath}`);
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
  public determineScopeForItem(item: SharepointContentItem, scopes?: Scope[]): string | undefined {
    if (!scopes || scopes.length === 0) {
      // Flat mode - return the configured scope ID
      return this.configService.get('unique.scopeId', { infer: true });
    }

    const rootScopeName = this.configService.get('unique.rootScopeName', {
      infer: true,
    });

    assert(rootScopeName, 'rootScopeName must be configured for recursive mode');

    const scopePath = buildScopePathFromItem(item, rootScopeName);

    // Find scope with this path.
    const scope = scopes.find((scope) => scope.path === scopePath);
    if (!scope?.id) {
      this.logger.warn(`Scope not found for path: ${scopePath}`);
      return undefined;
    }
    return scope.id;
  }
}
