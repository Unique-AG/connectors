import { Inject, Injectable, Logger } from '@nestjs/common';
import { type Histogram } from '@opentelemetry/api';
import { ConfigEmitEvent } from '../config/app.config';
import { ConfigDiagnosticsService } from '../config/config-diagnostics.service';
import { isAutoScope, type SiteConfig } from '../config/sharepoint.schema';
import { EnabledDisabledMode } from '../constants/enabled-disabled-mode.enum';
import { IngestionMode } from '../constants/ingestion.constants';
import { FullSyncStep, SiteSyncStep } from '../constants/sync-step.enum';
import { SPC_SYNC_DURATION_SECONDS } from '../metrics';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { SitesConfigurationService } from '../microsoft-apis/graph/sites-configuration.service';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { PermissionsSyncError } from '../permissions-sync/permissions-sync.error';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { Scope, ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { sanitizeError } from '../utils/normalize-error';
import { type Smeared, smearPath } from '../utils/smeared';
import { elapsedSeconds, elapsedSecondsLog } from '../utils/timing.util';
import { ContentSyncService } from './content-sync.service';
import { DeduplicateSitesQuery } from './deduplicate-sites.query';
import { FindRootScopeQuery } from './root-scope/find-root-scope.query';
import { InitializeRootScopeCommand } from './root-scope/initialize-root-scope.command';
import { RootScopeResolutionError } from './root-scope/root-scope-resolution.error';
import { ScopeManagementService } from './scope-management.service';
import { SharepointSyncContext } from './sharepoint-sync-context.interface';
import { DiscoveredSubsite, SubsiteDiscoveryService } from './subsite-discovery.service';
import type { FullSyncResult, SiteResultEntry, SiteSyncResult } from './sync-result.types';

export interface SynchronizeResult {
  fullResult: FullSyncResult;
  siteResults: SiteResultEntry[];
}

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
    private readonly subsiteDiscoveryService: SubsiteDiscoveryService,
    private readonly initializeRootScopeCommand: InitializeRootScopeCommand,
    private readonly findRootScopeQuery: FindRootScopeQuery,
    private readonly deduplicateSitesQuery: DeduplicateSitesQuery,
    @Inject(SPC_SYNC_DURATION_SECONDS)
    private readonly spcSyncDurationSeconds: Histogram,
  ) {}

  public async synchronize(): Promise<SynchronizeResult> {
    const syncStartTime = Date.now();
    if (this.isScanning) {
      this.logger.warn('Skipping scan - previous scan is still in progress.');
      const fullResult: FullSyncResult = { status: 'skipped', reason: 'scan_in_progress' };
      this.recordFullSyncMetric(syncStartTime, fullResult);
      return { fullResult, siteResults: [] };
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
        const fullResult: FullSyncResult = {
          status: 'failure',
          step: FullSyncStep.SitesConfigLoading,
        };
        this.recordFullSyncMetric(syncStartTime, fullResult);
        return { fullResult, siteResults: [] };
      }

      sites = this.deduplicateSitesQuery.execute(sites);

      const { active, deleted, inactive } = this.categorizeSites(sites);

      this.logger.log(
        `Sites configuration: ${active.length} active, ${inactive.length} inactive, ${deleted.length} marked for deletion`,
      );

      await this.processSiteDeletions(deleted);

      if (active.length === 0) {
        this.logger.warn('No active sites configured for synchronization');
        const fullResult: FullSyncResult = { status: 'skipped', reason: 'no_active_sites' };
        this.recordFullSyncMetric(syncStartTime, fullResult);
        return { fullResult, siteResults: [] };
      }

      this.logger.log(`Starting scan of ${active.length} active SharePoint sites...`);

      // Subsites are only addressable via compound IDs (hostname,siteCollectionId,webId) in the
      // Graph API — a plain UUID (webId alone) cannot retrieve a subsite. Therefore, any subsite
      // configured as a standalone site will always use a compound ID, and we only need to compare
      // compound IDs when deduplicating against discovered subsites.
      const configuredSubsiteIds = new Set(
        sites.map((site) => site.siteId.value).filter((siteId) => siteId.split(',').length === 3),
      );

      const siteResults: SiteResultEntry[] = [];

      for (const siteConfig of active) {
        const siteSyncStartTime = Date.now();

        const result = await this.syncSite(siteConfig, configuredSubsiteIds);
        this.recordSiteMetric(siteSyncStartTime, siteConfig.siteId, result);
        siteResults.push({ siteId: siteConfig.siteId.value, result });
      }

      this.logger.log(
        `SharePoint synchronization completed in ${elapsedSecondsLog(syncStartTime)}`,
      );
      const fullResult: FullSyncResult = { status: 'success' };
      this.recordFullSyncMetric(syncStartTime, fullResult);
      return { fullResult, siteResults };
    } catch (error) {
      this.logger.error({
        msg: 'Failed full synchronization',
        error: sanitizeError(error),
      });
      this.recordFullSyncMetric(syncStartTime, { status: 'failure', step: FullSyncStep.Unknown });
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

  private async processSingleSiteDeletion(siteConfig: SiteConfig): Promise<void> {
    const logPrefix = `[Site: ${siteConfig.siteId}]`;

    this.logger.log(`${logPrefix} Processing deleted site - resolving root scope`);

    let rootScopeId: string | undefined; // Kept here for error reporting
    try {
      // Lookup-only resolution: never moves, never creates. For fixed it's a direct getScopeById;
      // for auto, the finder consults externalId in new + legacy formats but skips the name-match
      // fallback (omitted siteName option).
      let rootScope: Scope | null;
      if (isAutoScope(siteConfig.scopeId)) {
        rootScope = await this.findRootScopeQuery.execute(siteConfig);
      } else {
        rootScope = await this.uniqueScopesService.getScopeById(siteConfig.scopeId.scopeId);
      }

      if (!rootScope) {
        this.logger.log(`${logPrefix} Root scope not found. Skipping deletion process.`);
        return;
      }

      rootScopeId = rootScope.id;

      await this.uniqueFilesService.deleteFilesBySiteId(siteConfig.siteId);
      await this.scopeManagementService.resetRootScope(rootScope.id, siteConfig.scopeId.type);

      this.logger.log(`${logPrefix} Successfully processed site deletion`);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to process site deletion. Continuing with other sites`,
        rootScopeId,
        error: sanitizeError(error),
      });
    }
  }

  private async processSiteDeletions(deletedSites: SiteConfig[]): Promise<void> {
    for (const siteConfig of deletedSites) {
      await this.processSingleSiteDeletion(siteConfig);
    }
  }

  // IMPORTANT: getSiteInfo must run before InitializeRootScopeCommand. The root scope init
  // permanently stamps the scope's externalId with the configured siteId. If that siteId is wrong,
  // the scope becomes locked to it and cannot be re-bound without manual intervention. Validating
  // the site exists via the Graph API first ensures we never claim a scope with a bogus siteId.
  private async initializeSiteContext(
    siteConfig: SiteConfig,
    logPrefix: string,
  ): Promise<{ context: SharepointSyncContext } | { failureStep: SiteSyncStep }> {
    let siteInfo: Awaited<ReturnType<GraphApiService['getSiteInfo']>>;
    try {
      siteInfo = await this.graphApiService.getSiteInfo(siteConfig.siteId);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to get site info`,
        error: sanitizeError(error),
      });
      return { failureStep: SiteSyncStep.SiteNameFetch };
    }

    try {
      const result = await this.initializeRootScopeCommand.execute(siteConfig, siteInfo.siteName);
      return {
        context: {
          siteConfig,
          siteName: siteInfo.siteName,
          managedPath: siteInfo.managedPath,
          serviceUserId: result.serviceUserId,
          rootPath: result.rootPath,
          rootScopeId: result.rootScopeId,
          isInitialSync: result.isInitialSync,
          discoveredSubsites: [],
        },
      };
    } catch (error) {
      const failureStep =
        error instanceof RootScopeResolutionError
          ? SiteSyncStep.RootScopeResolution
          : SiteSyncStep.RootScopeInit;
      this.logger.error({
        msg:
          failureStep === SiteSyncStep.RootScopeResolution
            ? `${logPrefix} Failed to resolve auto root scope`
            : `${logPrefix} Failed to initialize root scope`,
        error: sanitizeError(error),
      });
      return { failureStep };
    }
  }

  private async syncSite(
    siteConfig: SiteConfig,
    configuredSubsiteIds: Set<string>,
  ): Promise<SiteSyncResult> {
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

    let subsites: DiscoveredSubsite[] = [];
    if (context.siteConfig.subsitesScan === EnabledDisabledMode.Enabled) {
      try {
        subsites = await this.discoverSubsites(context, configuredSubsiteIds, logPrefix);
        context.discoveredSubsites = subsites;
      } catch (error) {
        this.logger.error({
          msg: `${logPrefix} Failed to discover subsites`,
          error: sanitizeError(error),
        });
        return { status: 'failure', step: SiteSyncStep.SubsiteDiscovery };
      }
    }

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
      return { status: 'failure', step: SiteSyncStep.SiteItemsFetch };
    }

    if (subsites.length > 0) {
      try {
        const subsiteResult = await this.fetchItemsForSubsites(subsites, context, logPrefix);
        items.push(...subsiteResult.items);
        directories.push(...subsiteResult.directories);
      } catch (error) {
        this.logger.error({
          msg: `${logPrefix} Failed to fetch subsite items`,
          error: sanitizeError(error),
        });
        return { status: 'failure', step: SiteSyncStep.SubsiteItemsFetch };
      }
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
        return { status: 'failure', step: SiteSyncStep.ScopesCreation };
      }
    }

    try {
      await this.contentSyncService.syncContentForSite(items, scopes, context);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to synchronize content`,
        error: sanitizeError(error),
      });
      return { status: 'failure', step: SiteSyncStep.ContentSync };
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
        const step =
          error instanceof PermissionsSyncError ? error.step : SiteSyncStep.UnknownPermissionsSync;
        return { status: 'failure', step };
      }
    }

    try {
      await this.scopeManagementService.deleteStaleScopes(siteConfig.siteId);
    } catch (error) {
      this.logger.warn({
        msg: `${logPrefix} Failed to clean up stale scopes`,
        error: sanitizeError(error),
      });
      return { status: 'failure', step: SiteSyncStep.StaleScopeCleanup };
    }

    return { status: 'success' };
  }

  private async discoverSubsites(
    context: SharepointSyncContext,
    configuredSubsiteIds: Set<string>,
    logPrefix: string,
  ): Promise<DiscoveredSubsite[]> {
    const subsites = await this.subsiteDiscoveryService.discoverAllSubsites(
      context.siteConfig.siteId,
      context.siteName,
      configuredSubsiteIds,
    );

    this.logger.log(`${logPrefix} Discovered ${subsites.length} subsites to sync`);

    return subsites;
  }

  private async fetchItemsForSubsites(
    subsites: DiscoveredSubsite[],
    context: SharepointSyncContext,
    logPrefix: string,
  ): Promise<{ items: SharepointContentItem[]; directories: SharepointDirectoryItem[] }> {
    const syncSiteId = context.siteConfig.siteId;
    const items: SharepointContentItem[] = [];
    const directories: SharepointDirectoryItem[] = [];

    for (const subsite of subsites) {
      this.logger.log(
        `${logPrefix} Fetching items for subsite ${smearPath(subsite.name)} with ID ${subsite.siteId}`,
      );
      const result = await this.graphApiService.getAllSiteItems(
        subsite.siteId,
        context.siteConfig.syncColumnName,
      );
      // Key subsite items under the parent siteId so they share the same ingestion key prefix.
      // This ensures the file diff (scoped to parentSiteId) sees all items and detects deletions
      // when a subsite is removed or reconfigured as a standalone site. The original siteId stays
      // intact for API calls (e.g. ASPX page content fetching).
      for (const item of result.items) {
        items.push({ ...item, syncSiteId });
      }
      for (const dir of result.directories) {
        directories.push({ ...dir, syncSiteId });
      }
    }

    return { items, directories };
  }
}
