import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueApiService } from '../unique-api/unique-api.service';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { buildScopePathFromItem } from '../utils/sharepoint.util';

export type ScopePathToIdMap = Record<string, string>;

@Injectable()
export class ScopeManagementService {
  private readonly logger = new Logger(ScopeManagementService.name);

  public constructor(
    private readonly configService: ConfigService,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly uniqueApiService: UniqueApiService,
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
        this.logger.warn(`Failed to build scope path for item: ${error}`);
      }
    }

    return itemIdToScopePathMap;
  }

  public async batchCreateScopes(items: SharepointContentItem[]): Promise<ScopePathToIdMap> {
    const rootScopeName = this.configService.get('unique.rootScopeName', {
      infer: true,
    });
    assert(rootScopeName, 'rootScopeName must be configured');

    const itemIdToScopePathMap = this.buildItemIdToScopePathMap(items, rootScopeName);
    const uniqueFolderPaths = new Set(itemIdToScopePathMap.values());

    if (uniqueFolderPaths.size === 0) {
      return {};
    }

    const uniqueToken = await this.uniqueAuthService.getToken();
    const scopes = await this.uniqueApiService.createScopesBasedOnPaths(
      Array.from(uniqueFolderPaths),
      uniqueToken,
    );

    const scopePathToIdRecord: ScopePathToIdMap = {};
    for (const scope of scopes) {
      scopePathToIdRecord[scope.name] = scope.id;
    }

    return scopePathToIdRecord;
  }

  public buildItemIdToScopeIdMap(
    items: SharepointContentItem[],
    scopePathToIdMap: ScopePathToIdMap | undefined,
  ): Map<string, string> {
    const itemIdToScopeIdMap = new Map<string, string>();
    const rootScopeName = this.configService.get('unique.rootScopeName', {
      infer: true,
    });

    if (!scopePathToIdMap || !rootScopeName) {
      return itemIdToScopeIdMap;
    }

    const itemIdToScopePathMap = this.buildItemIdToScopePathMap(items, rootScopeName);

    for (const [itemId, scopePath] of itemIdToScopePathMap) {
      const scopeId = scopePathToIdMap[scopePath];

      if (scopeId) {
        itemIdToScopeIdMap.set(itemId, scopeId);
      } else {
        this.logger.warn(`Scope not found in cache for path: ${scopePath}`);
      }
    }

    return itemIdToScopeIdMap;
  }
}
