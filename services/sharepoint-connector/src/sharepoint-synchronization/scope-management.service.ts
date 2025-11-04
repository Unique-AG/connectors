import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueApiService } from '../unique-api/unique-api.service';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { buildScopePathFromItem } from '../utils/sharepoint.util';

@Injectable()
export class ScopeManagementService {
  private readonly logger = new Logger(ScopeManagementService.name);

  public constructor(
    private readonly configService: ConfigService,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly uniqueApiService: UniqueApiService,
  ) {}

  public async batchCreateScopes(items: SharepointContentItem[]): Promise<Map<string, string>> {
    const ingestionScopeLocation = this.configService.get('unique.ingestionScopeLocation', {
      infer: true,
    });
    assert(ingestionScopeLocation, 'ingestionScopeLocation must be configured');

    // Extract unique folder paths
    const uniqueFolderPaths = new Set<string>();
    for (const item of items) {
      try {
        const fullScopePath = buildScopePathFromItem(item, ingestionScopeLocation);
        uniqueFolderPaths.add(fullScopePath);
      } catch (error) {
        this.logger.warn(`Failed to build scope path for item: ${error}`);
      }
    }

    if (uniqueFolderPaths.size === 0) {
      return new Map();
    }

    // Call generateScopesBasedOnPaths to create all scopes
    const uniqueToken = await this.uniqueAuthService.getToken();
    const scopes = await this.uniqueApiService.generateScopesBasedOnPaths(
      Array.from(uniqueFolderPaths),
      uniqueToken,
    );

    const scopeCache = new Map<string, string>();
    for (const scope of scopes) {
      scopeCache.set(scope.name, scope.id);
    }

    return scopeCache;
  }

  public buildItemScopeIdMap(
    items: SharepointContentItem[],
    ingestionScopeLocation: string | undefined,
    scopeCache: Map<string, string> | undefined,
  ): Map<string, string> {
    const map = new Map<string, string>();

    if (!scopeCache || !ingestionScopeLocation) {
      return map;
    }

    for (const item of items) {
      const scopeId = this.resolveItemScopeId(item, ingestionScopeLocation, scopeCache);
      if (scopeId) {
        map.set(item.item.id, scopeId);
      }
    }

    return map;
  }

  private resolveItemScopeId(
    item: SharepointContentItem,
    ingestionScopeLocation: string,
    scopeCache: Map<string, string>,
  ): string | undefined {
    try {
      const itemScopePath = buildScopePathFromItem(item, ingestionScopeLocation);
      const scopeId = scopeCache.get(itemScopePath);

      if (!scopeId) {
        this.logger.warn(`Scope not found in cache for path: ${itemScopePath}`);
      }

      return scopeId;
    } catch (error) {
      this.logger.warn(`Failed to build scope path for item: ${error}`);
      return undefined;
    }
  }
}
