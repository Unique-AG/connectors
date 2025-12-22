import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Histogram } from '@opentelemetry/api';
import { Config } from '../config';
import type { SiteConfig } from '../config/tenant-config.schema';
import { TenantConfigLoaderService } from '../config/tenant-config-loader.service';
import { IngestionMode } from '../constants/ingestion.constants';
import { SPC_SYNC_DURATION_SECONDS } from '../metrics';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { shouldConcealLogs, smear } from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';
import { elapsedSeconds, elapsedSecondsLog } from '../utils/timing.util';
import { ContentSyncService } from './content-sync.service';
import { ScopeManagementService } from './scope-management.service';
import type { BaseSyncContext, SharepointSyncContext } from './types';

@Injectable()
export class SharepointSynchronizationService {
  private readonly logger = new Logger(this.constructor.name);
  private isScanning = false;
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly graphApiService: GraphApiService,
    private readonly contentSyncService: ContentSyncService,
    private readonly permissionsSyncService: PermissionsSyncService,
    private readonly scopeManagementService: ScopeManagementService,
    private readonly tenantConfigLoaderService: TenantConfigLoaderService,
    @Inject(SPC_SYNC_DURATION_SECONDS)
    private readonly spcSyncDurationSeconds: Histogram,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.tenantConfigLoaderService);
  }

  public async synchronize(): Promise<void> {
    const syncStartTime = Date.now();
    if (this.isScanning) {
      this.logger.warn('Skipping scan - previous scan is still in progress.');
      this.spcSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
        sync_type: 'full',
        result: 'skipped',
        skip_reason: 'scan_in_progress',
      });
      return;
    }

    this.isScanning = true;

    // We wrap the whole action in a try-finally block to ensure that the isScanning flag is reset
    // in case of some unexpected one-off error occurring.
    try {
      // Load site configs from configured source (configDirectory or sharePointList)
      const siteConfigs = await this.tenantConfigLoaderService.loadConfig();

      if (siteConfigs.length === 0) {
        this.logger.error(
          'No site configurations found. Please configure site sources via tenant config files or SharePoint list.',
        );
        this.spcSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
          sync_type: 'full',
          result: 'skipped',
          skip_reason: 'no_sites_configured',
        });
        return;
      }

      const sitesToProcess = siteConfigs.map((config) => ({ siteId: config.siteId, config }));

      this.logger.log(`Starting scan with ${sitesToProcess.length} site config(s)...`);

      // Process each site configuration
      for (const { siteId, config } of sitesToProcess) {
        await this.processSite(
          siteId,
          config as SiteConfig & { scopeId: string; ingestionMode: IngestionMode },
          syncStartTime,
        );
      }

      this.logger.log(
        `SharePoint synchronization completed in ${elapsedSecondsLog(syncStartTime)}`,
      );
      this.spcSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
        sync_type: 'full',
        result: 'success',
      });
    } catch (error) {
      this.logger.error({
        msg: 'Failed full synchronization',
        error: sanitizeError(error),
      });
      this.spcSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
        sync_type: 'full',
        result: 'failure',
        failure_step: 'unknown',
      });
      throw error;
    } finally {
      this.isScanning = false;
    }
  }

  private async processSite(
    siteId: string,
    siteConfig: SiteConfig & { scopeId: string; ingestionMode: IngestionMode },
    _fullSyncStartTime: number,
  ): Promise<void> {
    const siteSyncStartTime = Date.now();
    const logSiteId = this.shouldConcealLogs ? smear(siteId) : siteId;
    const logPrefix = `[Site: ${logSiteId}]`;

    try {
      // Use site config values (no global fallbacks)
      const ingestionMode = siteConfig.ingestionMode;
      const scopeId = siteConfig.scopeId;
      const syncMode = siteConfig.syncMode;

      // Initialize root scope and context (once per site)
      let baseContext: BaseSyncContext;
      try {
        // todo: externalIds will be duplicated when we add another scopeId as rootScope - we might want to set the kb path also in the external id
        baseContext = await this.scopeManagementService.initializeRootScope(scopeId, ingestionMode);
      } catch (error) {
        this.logger.error({
          msg: `${logPrefix} Failed to initialize root scope`,
          error: sanitizeError(error),
        });
        this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
          sync_type: 'site',
          sp_site_id: logSiteId,
          result: 'failure',
          failure_step: 'root_scope_initialization',
        });
        return;
      }

      let scopes: ScopeWithPath[] | null = null;
      const siteStartTime = Date.now();

      const context: SharepointSyncContext = {
        ...baseContext,
        siteId,
        siteName: await this.graphApiService.getSiteName(siteId),
      };

      const { items, directories } = await this.graphApiService.getAllSiteItems(siteId);
      this.logger.log(`${logPrefix} Finished scanning in ${elapsedSecondsLog(siteStartTime)}`);

      if (items.length === 0) {
        this.logger.log(`${logPrefix} Found no items marked for synchronization.`);
        this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
          sync_type: 'site',
          sp_site_id: logSiteId,
          result: 'skipped',
          skip_reason: 'no_items_to_sync',
        });
        return;
      }

      if (ingestionMode === IngestionMode.Recursive) {
        try {
          // Create scopes for ALL paths (including moved file destinations)
          scopes = await this.scopeManagementService.batchCreateScopes(items, directories, context, siteConfig);
        } catch (error) {
          this.logger.error({
            msg: `${logPrefix} Failed to create scopes. Skipping site.`,
            error: sanitizeError(error),
          });
          this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
            sync_type: 'site',
            sp_site_id: logSiteId,
            result: 'failure',
            failure_step: 'scopes_creation',
          });
          return;
        }
      }

      try {
        await this.contentSyncService.syncContentForSite(items, scopes, context, siteConfig);
      } catch (error) {
        this.logger.error({
          msg: `${logPrefix} Failed to synchronize content`,
          error: sanitizeError(error),
        });
        this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
          sync_type: 'site',
          sp_site_id: logSiteId,
          result: 'failure',
          failure_step: 'content_sync',
        });
        return;
      }

      if (syncMode === 'content_and_permissions') {
        try {
          await this.permissionsSyncService.syncPermissionsForSite({
            context,
            sharePoint: { items, directories },
            unique: { folders: scopes },
          });
        } catch (error) {
          this.logger.error({
            msg: `${logPrefix} Failed to synchronize permissions`,
            error: sanitizeError(error),
          });
          this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
            sync_type: 'site',
            sp_site_id: logSiteId,
            result: 'failure',
            failure_step: 'permissions_sync',
          });
          return;
        }
      }

      this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
        sync_type: 'site',
        sp_site_id: logSiteId,
        result: 'success',
      });
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Unexpected error during site processing`,
        error: sanitizeError(error),
      });
      this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
        sync_type: 'site',
        sp_site_id: this.shouldConcealLogs ? smear(siteId) : siteId,
        result: 'failure',
        failure_step: 'unknown',
      });
    }
  }
}
