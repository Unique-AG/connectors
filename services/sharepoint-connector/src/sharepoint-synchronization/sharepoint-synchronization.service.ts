import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { IngestionMode } from '../constants/ingestion.constants';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import type { Scope } from '../unique-api/unique-api.types';
import { normalizeError } from '../utils/normalize-error';
import { elapsedSecondsLog } from '../utils/timing.util';
import { ContentSyncService } from './content-sync.service';
import { ScopeManagementService, type ScopePathToIdMap } from './scope-management.service';

@Injectable()
export class SharepointSynchronizationService {
  private readonly logger = new Logger(this.constructor.name);
  private isScanning = false;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly graphApiService: GraphApiService,
    private readonly contentSyncService: ContentSyncService,
    private readonly permissionsSyncService: PermissionsSyncService,
    private readonly scopeManagementService: ScopeManagementService,
  ) {}

  public async synchronize(): Promise<void> {
    if (this.isScanning) {
      this.logger.warn(
        'Skipping scan - previous scan is still in progress. This prevents overlapping scans.',
      );
      return;
    }

    this.isScanning = true;
    const syncStartTime = Date.now();
    const siteIdsToScan = this.configService.get('sharepoint.siteIds', { infer: true });
    const ingestionMode = this.configService.get('unique.ingestionMode', { infer: true });

    this.logger.log(`Starting scan of ${siteIdsToScan.length} SharePoint sites...`);

    for (const siteId of siteIdsToScan) {
      const logPrefix = `[SiteId: ${siteId}]`;

      const siteStartTime = Date.now();
      const items = await this.graphApiService.getAllSiteItems(siteId);
      this.logger.log(`${logPrefix} Finished scanning in ${elapsedSecondsLog(siteStartTime)}`);

      if (items.length === 0) {
        this.logger.warn(`${logPrefix} Found no items marked for synchronization.`);
        continue;
      }

      // TODO make sure that scope ingestion works now that we've changed to file-diff v2
      // TODO implement file deletion and file moving
      // Create scopes for recursive mode
      let scopePathToIdMap: ScopePathToIdMap | undefined;
      let itemIdToScopePathMap: Map<string, string> | undefined;

      if (ingestionMode === IngestionMode.Recursive) {
        const result = await this.getOrCreateScopesForPaths(items);
        if (!result) {
          this.logger.error(`${logPrefix} Failed to create scopes`);
          continue;
        }
        scopePathToIdMap = result.scopePathToIdMap;
        itemIdToScopePathMap = result.itemIdToScopePathMap;
        // TODO the scopes array will be useful for syncPermissionsForSite
      }

      try {
        // Start processing sitePages and files
        await this.contentSyncService.syncContentForSite(
          siteId,
          items,
          scopePathToIdMap,
          itemIdToScopePathMap,
        );
      } catch (error) {
        this.logger.error({
          msg: `${logPrefix} Failed to synchronize content: ${normalizeError(error).message}`,
          err: error,
        });
        continue;
      }

      const syncMode = this.configService.get('processing.syncMode', { infer: true });
      if (syncMode === 'content-and-permissions') {
        try {
          await this.permissionsSyncService.syncPermissionsForSite(siteId, items);
        } catch (error) {
          this.logger.error({
            msg: `${logPrefix} Failed to synchronize permissions: ${normalizeError(error).message}`,
            err: error,
          });
        }
      }
    }

    this.logger.log(`SharePoint synchronization completed in ${elapsedSecondsLog(syncStartTime)}`);
    this.isScanning = false;
  }

  private async getOrCreateScopesForPaths(items: SharepointContentItem[]): Promise<
    | {
        scopes: Scope[];
        scopePathToIdMap: ScopePathToIdMap;
        itemIdToScopePathMap: Map<string, string>;
      }
    | undefined
  > {
    const siteId = items[0]?.siteId || 'unknown siteId';
    try {
      return await this.scopeManagementService.batchCreateScopes(items);
    } catch (error) {
      // TODO what happens if generating scopes fails? Do we stop the sync for this site?
      this.logger.error({
        msg: `[SiteId: ${siteId}] Failed to create scopes: ${normalizeError(error).message}`,
        err: error,
      });
      return;
    }
  }
}
