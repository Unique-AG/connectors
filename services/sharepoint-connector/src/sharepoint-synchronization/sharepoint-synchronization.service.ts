import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Histogram, ValueType } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import { Config } from '../config';
import { IngestionMode } from '../constants/ingestion.constants';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { normalizeError } from '../utils/normalize-error';
import { elapsedSeconds, elapsedSecondsLog } from '../utils/timing.util';
import { ContentSyncService } from './content-sync.service';
import { ScopeManagementService } from './scope-management.service';
import type { BaseSyncContext, SharepointSyncContext } from './types';

@Injectable()
export class SharepointSynchronizationService {
  private readonly logger = new Logger(this.constructor.name);
  private isScanning = false;

  private readonly spcSiteSyncDurationSeconds: Histogram;
  private readonly spcFullSyncDurationSeconds: Histogram;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly graphApiService: GraphApiService,
    private readonly contentSyncService: ContentSyncService,
    private readonly permissionsSyncService: PermissionsSyncService,
    private readonly scopeManagementService: ScopeManagementService,
    private readonly metricService: MetricService,
  ) {
    this.spcSiteSyncDurationSeconds = this.metricService.getHistogram(
      'spc_site_sync_duration_seconds',
      {
        description: 'Duration of a SharePoint site sync cycle',
        valueType: ValueType.DOUBLE,
        advice: {
          explicitBucketBoundaries: [10, 30, 60, 300, 600, 1800],
        },
      },
    );
    this.spcFullSyncDurationSeconds = this.metricService.getHistogram(
      'spc_full_sync_duration_seconds',
      {
        description: 'Duration of a full SharePoint synchronization cycle',
        valueType: ValueType.DOUBLE,
        advice: {
          explicitBucketBoundaries: [30, 60, 300, 600, 1800, 3600],
        },
      },
    );
  }

  public async synchronize(): Promise<void> {
    const syncStartTime = Date.now();
    if (this.isScanning) {
      this.logger.warn('Skipping scan - previous scan is still in progress.');
      this.spcFullSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
        result: 'skipped',
      });
      return;
    }

    this.isScanning = true;

    // We wrap the whole action in a try-finally block to ensure that the isScanning flag is reset
    // in case of some unexpected one-off error occurring.
    try {
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
        this.spcFullSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
          result: 'failure',
          failureStep: 'root_scope_initialization',
        });
        return;
      }

      this.logger.log(`Starting scan of ${siteIdsToScan.length} SharePoint sites...`);

      for (const siteId of siteIdsToScan) {
        const siteSyncStartTime = Date.now();
        const logPrefix = `[SiteId: ${siteId}]`;
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
            this.spcSiteSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
              sp_site_id: siteId, // TODO: Smear based on logging policy
              result: 'failure',
              failureStep: 'scopes_creation',
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
          this.spcSiteSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
            sp_site_id: siteId, // TODO: Smear based on logging policy
            result: 'failure',
            failureStep: 'content_sync',
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
            this.spcSiteSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
              sp_site_id: siteId, // TODO: Smear based on logging policy
              result: 'failure',
              failureStep: 'permissions_sync',
            });
            continue;
          }
        }

        this.spcSiteSyncDurationSeconds.record(elapsedSeconds(siteSyncStartTime), {
          sp_site_id: siteId, // TODO: Smear based on logging policy
          result: 'success',
        });
      }

      this.logger.log(
        `SharePoint synchronization completed in ${elapsedSecondsLog(syncStartTime)}`,
      );
      this.spcFullSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
        result: 'success',
      });
    } catch (error) {
      this.logger.error({
        msg: `Failed full synchronization: ${normalizeError(error).message}`,
        error,
      });
      this.spcFullSyncDurationSeconds.record(elapsedSeconds(syncStartTime), {
        result: 'failure',
        failureStep: 'unknown',
      });
    } finally {
      this.isScanning = false;
    }
  }
}
