import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { IngestionMode } from '../constants/ingestion.constants';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { concealLogs, smear } from '../utils/logging.util';
import { normalizeError } from '../utils/normalize-error';
import { elapsedSecondsLog } from '../utils/timing.util';
import { ContentSyncService } from './content-sync.service';
import { ScopeManagementService } from './scope-management.service';
import type { BaseSyncContext, SharepointSyncContext } from './types';

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
      this.logger.warn('Skipping scan - previous scan is still in progress.');
      return;
    }

    this.isScanning = true;

    // We wrap the whole action in a try-finally block to ensure that the isScanning flag is reset
    // in case of some unexpected one-off error occurring.
    try {
      const syncStartTime = Date.now();
      const siteIdsToScan = this.configService.get('sharepoint.siteIds', { infer: true });
      const ingestionMode = this.configService.get('unique.ingestionMode', { infer: true });
      const scopeId = this.configService.get('unique.scopeId', { infer: true });

      // Initialize root scope and context (once)
      let baseContext: BaseSyncContext;
      try {
        baseContext = await this.scopeManagementService.initializeRootScope(scopeId, ingestionMode);
      } catch (error) {
        this.logger.error({
          msg: `Failed to initialize root scope: ${normalizeError(error).message}`,
          error,
        });
        return;
      }

      this.logger.log(`Starting scan of ${siteIdsToScan.length} SharePoint sites...`);

      for (const siteId of siteIdsToScan) {
        const logPrefix = `[SiteId: ${concealLogs(this.configService) ? smear(siteId) : siteId}]`;
        let scopes: ScopeWithPath[] | null = null;
        const siteStartTime = Date.now();

        const context: SharepointSyncContext = {
          ...baseContext,
          siteId,
        };

        const { items, directories } = await this.graphApiService.getAllSiteItems(siteId);
        this.logger.log(`${logPrefix} Finished scanning in ${elapsedSecondsLog(siteStartTime)}`);

        if (items.length === 0) {
          this.logger.log(`${logPrefix} Found no items marked for synchronization.`);
          continue;
        }

        if (ingestionMode === IngestionMode.Recursive) {
          try {
            // Create scopes for ALL paths (including moved file destinations)
            scopes = await this.scopeManagementService.batchCreateScopes(items, context);
          } catch (error) {
            this.logger.error({
              msg: `${logPrefix} Failed to create scopes: ${normalizeError(error).message}. Skipping site.`,
              error,
            });
            continue;
          }
        }

        try {
          await this.contentSyncService.syncContentForSite(items, scopes, context);
        } catch (error) {
          this.logger.error({
            msg: `${logPrefix} Failed to synchronize content: ${normalizeError(error).message}`,
            error,
          });
          continue;
        }

        const syncMode = this.configService.get('processing.syncMode', { infer: true });
        if (syncMode === 'content_and_permissions') {
          try {
            await this.permissionsSyncService.syncPermissionsForSite({
              context,
              sharePoint: { items, directories },
              unique: { folders: scopes },
            });
          } catch (error) {
            this.logger.error({
              msg: `${logPrefix} Failed to synchronize permissions: ${normalizeError(error).message}`,
              error,
            });
          }
        }
      }

      this.logger.log(
        `SharePoint synchronization completed in ${elapsedSecondsLog(syncStartTime)}`,
      );
    } finally {
      this.isScanning = false;
    }
  }
}
