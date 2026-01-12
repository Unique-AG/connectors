import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Histogram } from '@opentelemetry/api';
import { Config } from '../config';
import type { SiteConfig } from '../config/tenant-config.schema';
import { IngestionMode } from '../constants/ingestion.constants';
import { SPC_SYNC_DURATION_SECONDS } from '../metrics';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import { UniqueFileIngestionService } from '../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { shouldConcealLogs, smear } from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';
import { elapsedSeconds, elapsedSecondsLog } from '../utils/timing.util';
import { ContentSyncService } from './content-sync.service';
import { RootScopeInfo, ScopeManagementService } from './scope-management.service';
import { SharepointSyncContext } from './sharepoint-sync-context.interface';

type SiteSyncResult =
  | { status: 'success' }
  | { status: 'failure'; step: string }
  | { status: 'skipped'; reason: string };

@Injectable()
export class SharepointSynchronizationService {
  private readonly logger = new Logger(this.constructor.name);
  private isScanning = false;
  private readonly shouldConcealLogs: boolean;

  private readonly MetricSteps = {
    SITES_CONFIG_LOADING: 'sites_config_loading',
    ROOT_SCOPE_INIT: 'root_scope_initialization',
    SITE_NAME_FETCH: 'site_name_fetch',
    SITE_ITEMS_FETCH: 'site_items_fetch',
    SCOPES_CREATION: 'scopes_creation',
    CONTENT_SYNC: 'content_sync',
    PERMISSIONS_SYNC: 'permissions_sync',
  } as const;

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
          failure_step: this.MetricSteps.SITES_CONFIG_LOADING,
        });
        return;
      }

      const { active, deleted, inactive } = this.categorizeSites(sites);

      this.logger.log(
        `Sites configuration: ${active.length} active, ${inactive.length} inactive, ${deleted.length} marked for deletion`,
      );

      await this.processSiteDeletions(deleted);

      if (active.length === 0) {
        this.logger.warn('No active sites configured for synchronization');
        this.spcSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
          sync_type: 'full',
          result: 'skipped',
          skip_reason: 'no_active_sites',
        });
        return;
      }

      this.logger.log(`Starting scan of ${active.length} active SharePoint sites...`);

      for (const siteConfig of active) {
        const siteSyncStartTime = Date.now();
        const logSiteId = this.shouldConcealLogs ? smear(siteConfig.siteId) : siteConfig.siteId;

        const result = await this.syncSite(siteConfig);
        this.recordSiteMetric(siteSyncStartTime, logSiteId, result);
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

  private recordSiteMetric(startTime: number, logSiteId: string, result: SiteSyncResult): void {
    this.spcSyncDurationSeconds.record(elapsedSeconds(startTime), {
      sync_type: 'site',
      sp_site_id: logSiteId,
      result: result.status,
      ...(result.status === 'failure' && { failure_step: result.step }),
      ...(result.status === 'skipped' && { skip_reason: result.reason }),
    });
  }

  private categorizeSites(sites: SiteConfig[]) {
    return {
      active: sites.filter((site) => site.syncStatus === 'active'),
      deleted: sites.filter((site) => site.syncStatus === 'deleted'),
      inactive: sites.filter((site) => site.syncStatus === 'inactive'),
    };
  }

  private async processSingleSiteDeletion(siteConfig: SiteConfig): Promise<void> {
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

  private async processSiteDeletions(deletedSites: SiteConfig[]): Promise<void> {
    for (const siteConfig of deletedSites) {
      await this.processSingleSiteDeletion(siteConfig);
    }
  }

  private async initializeSiteContext(
    siteConfig: SiteConfig,
    logPrefix: string,
  ): Promise<{ context: SharepointSyncContext } | { failureStep: string }> {
    let baseContext: RootScopeInfo;
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
      return { failureStep: this.MetricSteps.ROOT_SCOPE_INIT };
    }

    let siteName: string;
    try {
      siteName = await this.graphApiService.getSiteName(siteConfig.siteId);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to get site name`,
        error: sanitizeError(error),
      });
      return { failureStep: this.MetricSteps.SITE_NAME_FETCH };
    }

    return {
      context: {
        siteConfig,
        siteName,
        serviceUserId: baseContext.serviceUserId,
        rootPath: baseContext.rootPath,
      },
    };
  }

  private async syncSite(siteConfig: SiteConfig): Promise<SiteSyncResult> {
    const logSiteId = this.shouldConcealLogs ? smear(siteConfig.siteId) : siteConfig.siteId;
    const logPrefix = `[Site: ${logSiteId}]`;
    let scopes: ScopeWithPath[] | null = null;
    const siteStartTime = Date.now();

    const initResult = await this.initializeSiteContext(siteConfig, logPrefix);
    if ('failureStep' in initResult) {
      return { status: 'failure', step: initResult.failureStep };
    }
    const { context } = initResult;

    let items: SharepointContentItem[];
    let directories: SharepointDirectoryItem[];

    try {
      const result = await this.graphApiService.getAllSiteItems(
        context.siteConfig.siteId,
        context.siteConfig.syncColumnName,
      );
      items = result.items;
      directories = result.directories;
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to get site items`,
        error: sanitizeError(error),
      });
      return { status: 'failure', step: this.MetricSteps.SITE_ITEMS_FETCH };
    }

    this.logger.log(`${logPrefix} Finished scanning in ${elapsedSecondsLog(siteStartTime)}`);

    if (items.length === 0) {
      this.logger.log(`${logPrefix} Found no items marked for synchronization.`);
      return { status: 'skipped', reason: 'no_items_to_sync' };
    }

    if (context.siteConfig.ingestionMode === IngestionMode.Recursive) {
      try {
        scopes = await this.scopeManagementService.batchCreateScopes(items, directories, context);
      } catch (error) {
        this.logger.error({
          msg: `${logPrefix} Failed to create scopes. Skipping site.`,
          error: sanitizeError(error),
        });
        return { status: 'failure', step: this.MetricSteps.SCOPES_CREATION };
      }
    }

    try {
      await this.contentSyncService.syncContentForSite(items, scopes, context);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to synchronize content`,
        error: sanitizeError(error),
      });
      return { status: 'failure', step: this.MetricSteps.CONTENT_SYNC };
    }

    if (context.siteConfig.syncMode === 'content_and_permissions') {
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
        return { status: 'failure', step: this.MetricSteps.PERMISSIONS_SYNC };
      }
    }

    return { status: 'success' };
  }
}
