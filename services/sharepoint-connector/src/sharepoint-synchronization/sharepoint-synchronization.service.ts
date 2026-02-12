import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { type Histogram } from '@opentelemetry/api';
import { entries, groupBy } from 'remeda';
import { ConfigEmitEvent } from '../config/app.config';
import { ConfigDiagnosticsService } from '../config/config-diagnostics.service';
import type { SiteConfig } from '../config/sharepoint.schema';
import { IngestionMode } from '../constants/ingestion.constants';
import { SyncStep } from '../constants/sync-step.enum';
import { SPC_SYNC_DURATION_SECONDS } from '../metrics';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { SitesConfigurationService } from '../microsoft-apis/graph/sites-configuration.service';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { sanitizeError } from '../utils/normalize-error';
import type { Smeared } from '../utils/smeared';
import { elapsedSeconds, elapsedSecondsLog } from '../utils/timing.util';
import { ContentSyncService } from './content-sync.service';
import { RootScopeInfo, ScopeManagementService } from './scope-management.service';
import { SharepointSyncContext } from './sharepoint-sync-context.interface';

type SiteSyncResult =
  | { status: 'success' }
  | { status: 'failure'; step: SyncStep }
  | { status: 'skipped'; reason: string };

export type FullSyncResult =
  | { status: 'success' }
  | { status: 'failure'; step: SyncStep }
  | { status: 'skipped'; reason: string };

@Injectable()
export class SharepointSynchronizationService {
  private readonly logger = new Logger(this.constructor.name);
  private isScanning = false;

  public constructor(
    private readonly graphApiService: GraphApiService,
    private readonly sitesConfigurationService: SitesConfigurationService,
    private readonly contentSyncService: ContentSyncService,
    private readonly permissionsSyncService: PermissionsSyncService,
    private readonly scopeManagementService: ScopeManagementService,
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly configDiagnosticsService: ConfigDiagnosticsService,
    @Inject(SPC_SYNC_DURATION_SECONDS)
    private readonly spcSyncDurationSeconds: Histogram,
  ) {}

  public async synchronize(): Promise<FullSyncResult> {
    const syncStartTime = Date.now();
    if (this.isScanning) {
      this.logger.warn('Skipping scan - previous scan is still in progress.');
      const result: FullSyncResult = { status: 'skipped', reason: 'scan_in_progress' };
      this.recordFullSyncMetric(syncStartTime, result);
      return result;
    }

    this.isScanning = true;

    try {
      let sites: SiteConfig[];
      try {
        sites = await this.sitesConfigurationService.loadSitesConfiguration();
      } catch (error) {
        this.logger.error({
          msg: 'Failed to load sites configuration',
          error: sanitizeError(error),
        });
        const result: FullSyncResult = {
          status: 'failure',
          step: SyncStep.SitesConfigLoading,
        };
        this.recordFullSyncMetric(syncStartTime, result);
        return result;
      }

      sites = this.deduplicateByScopeId(sites);

      const { active, deleted, inactive } = this.categorizeSites(sites);

      this.logger.log(
        `Sites configuration: ${active.length} active, ${inactive.length} inactive, ${deleted.length} marked for deletion`,
      );

      await this.processSiteDeletions(deleted);

      if (active.length === 0) {
        this.logger.warn('No active sites configured for synchronization');
        const result: FullSyncResult = { status: 'skipped', reason: 'no_active_sites' };
        this.recordFullSyncMetric(syncStartTime, result);
        return result;
      }

      this.logger.log(`Starting scan of ${active.length} active SharePoint sites...`);

      const siteResults: SiteSyncResult[] = [];
      for (const siteConfig of active) {
        const siteSyncStartTime = Date.now();

        const siteResult = await this.syncSite(siteConfig);
        this.recordSiteMetric(siteSyncStartTime, siteConfig.siteId, siteResult);
        siteResults.push(siteResult);
      }

      this.logger.log(
        `SharePoint synchronization completed in ${elapsedSecondsLog(syncStartTime)}`,
      );

      const failedSite = siteResults.find((r) => r.status === 'failure');
      if (failedSite) {
        const result: FullSyncResult = { status: 'failure', step: failedSite.step };
        this.recordFullSyncMetric(syncStartTime, result);
        return result;
      }

      const result: FullSyncResult = { status: 'success' };
      this.recordFullSyncMetric(syncStartTime, result);
      return result;
    } catch (error) {
      this.logger.error({
        msg: 'Failed full synchronization',
        error: sanitizeError(error),
      });
      this.spcSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
        sync_type: 'full',
        result: 'failure',
        failure_step: SyncStep.Unknown,
      });
      throw error;
    } finally {
      this.isScanning = false;
    }
  }

  private recordFullSyncMetric(startTime: number, result: FullSyncResult): void {
    this.spcSyncDurationSeconds.record(elapsedSeconds(startTime), {
      sync_type: 'full',
      result: result.status,
      ...(result.status === 'failure' && { failure_step: result.step }),
      ...(result.status === 'skipped' && { skip_reason: result.reason }),
    });
  }

  private recordSiteMetric(startTime: number, siteId: Smeared, result: SiteSyncResult): void {
    this.spcSyncDurationSeconds.record(elapsedSeconds(startTime), {
      sync_type: 'site',
      sp_site_id: siteId.toString(),
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

  private deduplicateByScopeId(sites: SiteConfig[]): SiteConfig[] {
    const groups = groupBy(sites, (site) => site.scopeId);

    return entries(groups).map(([scopeId, group]) => {
      if (group.length > 1) {
        this.logDuplicateScopeId(scopeId, group);
      }
      const site = group[0];
      assert.ok(site, `No site configuration found for scopeId: ${scopeId}`);
      return site;
    });
  }

  private logDuplicateScopeId(
    scopeId: string,
    sitesWithSameScopeId: ReadonlyArray<SiteConfig>,
  ): void {
    this.logger.error('DUPLICATE SCOPE ID DETECTED!');
    this.logger.error(`ScopeId: ${scopeId} is configured for multiple sites:`);

    for (const [index, site] of sitesWithSameScopeId.entries()) {
      const status = index === 0 ? 'WILL SYNC - first occurrence' : 'SKIPPED - duplicate scopeId';
      this.logger.error(`  - siteId: ${site.siteId} (${status})`);
    }
    this.logger.error('Only the first site will be synchronized.');
  }

  private async processSingleSiteDeletion(siteConfig: SiteConfig): Promise<void> {
    const logPrefix = `[Site: ${siteConfig.siteId}]`;

    this.logger.log(
      `${logPrefix} Processing site marked for deletion (ScopeId: ${siteConfig.scopeId})`,
    );

    try {
      const rootScope = await this.uniqueScopesService.getScopeById(siteConfig.scopeId);

      if (!rootScope) {
        this.logger.log(
          `${logPrefix} Root scope ${siteConfig.scopeId} not found. Skipping deletion process.`,
        );
        return;
      }

      await this.uniqueFilesService.deleteFilesBySiteId(siteConfig.siteId);
      await this.scopeManagementService.deleteRootScopeRecursively(siteConfig.scopeId);

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
  ): Promise<{ context: SharepointSyncContext } | { failureStep: SyncStep }> {
    let baseContext: RootScopeInfo;
    try {
      baseContext = await this.scopeManagementService.initializeRootScope(
        siteConfig.scopeId,
        siteConfig.siteId,
        siteConfig.ingestionMode,
      );
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to initialize root scope`,
        error: sanitizeError(error),
      });
      return { failureStep: SyncStep.RootScopeInit };
    }

    let siteName: Smeared;
    try {
      siteName = await this.graphApiService.getSiteName(siteConfig.siteId);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to get site name`,
        error: sanitizeError(error),
      });
      return { failureStep: SyncStep.SiteNameFetch };
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
    const logPrefix = `[Site: ${siteConfig.siteId}]`;
    let scopes: ScopeWithPath[] | null = null;
    const siteStartTime = Date.now();

    if (this.configDiagnosticsService.shouldLogConfig(ConfigEmitEvent.ON_SYNC)) {
      this.configDiagnosticsService.logConfig(`${logPrefix} Site Config`, siteConfig);
    }

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
      return { status: 'failure', step: SyncStep.SiteItemsFetch };
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
        return { status: 'failure', step: SyncStep.ScopesCreation };
      }
    }

    try {
      await this.contentSyncService.syncContentForSite(items, scopes, context);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to synchronize content`,
        error: sanitizeError(error),
      });
      return { status: 'failure', step: SyncStep.ContentSync };
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
        return { status: 'failure', step: SyncStep.PermissionsSync };
      }
    }

    return { status: 'success' };
  }
}
