import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Histogram } from '@opentelemetry/api';
import { Config } from '../config';
import type { SiteConfig } from '../config/tenant-config.schema';
import { IngestionMode } from '../constants/ingestion.constants';
import { SPC_SYNC_DURATION_SECONDS } from '../metrics';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import { UniqueFileIngestionService } from '../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
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
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly uniqueFileIngestionService: UniqueFileIngestionService,
    private readonly uniqueScopesService: UniqueScopesService,
    @Inject(SPC_SYNC_DURATION_SECONDS)
    private readonly spcSyncDurationSeconds: Histogram,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
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
      let sites: SiteConfig[];
      try {
        sites = await this.graphApiService.loadSitesConfiguration();
      } catch (error) {
        this.logger.error({
          msg: 'Failed to load sites configuration',
          error: sanitizeError(error),
        });
        this.spcSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
          sync_type: 'full',
          result: 'failure',
          failure_step: 'sites_config_loading',
        });
        return;
      }

      const activeSites = sites.filter((site) => site.syncStatus === 'active');
      const deletedSites = sites.filter((site) => site.syncStatus === 'deleted');
      const inactiveSites = sites.filter((site) => site.syncStatus === 'inactive');

      this.logger.log(
        `Sites configuration: ${activeSites.length} active, ${inactiveSites.length} inactive, ${deletedSites.length} marked for deletion`,
      );

      for (const siteConfig of deletedSites) {
        const logSiteId = this.shouldConcealLogs ? smear(siteConfig.siteId) : siteConfig.siteId;
        const logPrefix = `[Site: ${logSiteId}]`;

        this.logger.log(
          `${logPrefix} Processing site marked for deletion (ScopeId: ${siteConfig.scopeId})`,
        );

        try {
          const files = await this.uniqueFilesService.getFilesForSite(siteConfig.siteId);

          if (files.length > 0) {
            this.logger.log(`${logPrefix} Deleting ${files.length} files`);
            await this.uniqueFileIngestionService.deleteContentByContentIds(files.map((f) => f.id));
          }

          const rootScope = await this.uniqueScopesService.getScopeById(siteConfig.scopeId);

          if (rootScope) {
            await this.scopeManagementService.deleteRootScopeRecursively(siteConfig.scopeId);
          } else {
            this.logger.warn(
              `${logPrefix} Root scope ${siteConfig.scopeId} not found. It was already deleted`,
            );
          }

          this.logger.log(`${logPrefix} Successfully processed deletion`);
        } catch (error) {
          this.logger.error({
            msg: `${logPrefix} Failed to process site deletion. Continuing with other sites`,
            scopeId: siteConfig.scopeId,
            error: sanitizeError(error),
          });
        }
      }

      if (activeSites.length === 0) {
        this.logger.warn('No active sites configured for synchronization');
        this.spcSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
          sync_type: 'full',
          result: 'skipped',
          skip_reason: 'no_active_sites',
        });
        return;
      }

      this.logger.log(`Starting scan of ${activeSites.length} active SharePoint sites...`);

      for (const siteConfig of activeSites) {
        const siteSyncStartTime = Date.now();
        const logSiteId = this.shouldConcealLogs ? smear(siteConfig.siteId) : siteConfig.siteId;
        const logPrefix = `[Site: ${logSiteId}]`;
        let scopes: ScopeWithPath[] | null = null;
        const siteStartTime = Date.now();

        // Initialize root scope for this site
        let baseContext: BaseSyncContext;
        try {
          baseContext = await this.scopeManagementService.initializeRootScope(
            siteConfig.scopeId,
            siteConfig.ingestionMode,
          );
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
          continue;
        }

        let siteName: string;
        try {
          siteName = await this.graphApiService.getSiteName(siteConfig.siteId);
        } catch (error) {
          this.logger.error({
            msg: `${logPrefix} Failed to get site name`,
            error: sanitizeError(error),
          });
          this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
            sync_type: 'site',
            sp_site_id: logSiteId,
            result: 'failure',
            failure_step: 'site_name_fetch',
          });
          continue;
        }

        const context: SharepointSyncContext = {
          ...baseContext,
          ...siteConfig,
          siteName,
        };

        let items: Awaited<ReturnType<typeof this.graphApiService.getAllSiteItems>>['items'];
        let directories: Awaited<
          ReturnType<typeof this.graphApiService.getAllSiteItems>
        >['directories'];
        try {
          const result = await this.graphApiService.getAllSiteItems(
            context.siteId,
            context.syncColumnName,
          );
          items = result.items;
          directories = result.directories;
        } catch (error) {
          this.logger.error({
            msg: `${logPrefix} Failed to get site items`,
            error: sanitizeError(error),
          });
          this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
            sync_type: 'site',
            sp_site_id: logSiteId,
            result: 'failure',
            failure_step: 'site_items_fetch',
          });
          continue;
        }
        this.logger.log(`${logPrefix} Finished scanning in ${elapsedSecondsLog(siteStartTime)}`);

        if (items.length === 0) {
          this.logger.log(`${logPrefix} Found no items marked for synchronization.`);
          this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
            sync_type: 'site',
            sp_site_id: logSiteId,
            result: 'skipped',
            skip_reason: 'no_items_to_sync',
          });
          continue;
        }

        if (context.ingestionMode === IngestionMode.Recursive) {
          try {
            // Create scopes for ALL paths (including moved file destinations)
            scopes = await this.scopeManagementService.batchCreateScopes(
              items,
              directories,
              context,
            );
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
            continue;
          }
        }

        try {
          await this.contentSyncService.syncContentForSite(items, scopes, context);
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
          continue;
        }

        if (context.syncMode === 'content_and_permissions') {
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
            continue;
          }
        }

        this.spcSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
          sync_type: 'site',
          sp_site_id: logSiteId,
          result: 'success',
        });
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
}
