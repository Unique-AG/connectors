import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { IngestionMode } from '../constants/ingestion.constants';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import type { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { normalizeError } from '../utils/normalize-error';
import { elapsedSecondsLog } from '../utils/timing.util';
import { ContentSyncService } from './content-sync.service';
import { ScopeManagementService } from './scope-management.service';

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

      // TODO implement file deletion and file moving
      const scopes = await this.createScopesForRecursiveIngestion(items, ingestionMode, logPrefix);
      if (scopes === undefined && ingestionMode === IngestionMode.Recursive) {
        continue; // Scope creation failed for recursive ingestion, skip this site
      }

      try {
        await this.contentSyncService.syncContentForSite(siteId, items, scopes);
      } catch (error) {
        this.logger.error({
          msg: `${logPrefix} Failed to synchronize content: ${normalizeError(error).message}`,
          err: error,
        });
        continue;
      }

      const syncMode = this.configService.get('processing.syncMode', { infer: true });
      if (syncMode === 'content_and_permissions') {
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

  private async createScopesForRecursiveIngestion(
    items: SharepointContentItem[],
    ingestionMode: IngestionMode,
    logPrefix: string,
  ): Promise<Scope[] | undefined> {
    if (ingestionMode !== IngestionMode.Recursive) {
      return;
    }

    try {
      const scopes = await this.scopeManagementService.batchCreateScopes(items);
      if (!scopes || scopes.length === 0) {
        this.logger.error(
          `${logPrefix} No scopes created for recursive ingestion mode, skipping synchronization`,
        );
        return;
      }
      return scopes;
    } catch (error) {
      // If generating scopes fails, we stop the sync for this site
      this.logger.error({
        msg: `${logPrefix} Failed to create scopes: ${normalizeError(error).message}`,
        err: error,
      });
      return;
    }
  }
}
