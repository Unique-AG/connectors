import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { GraphApiService } from '../msgraph/graph-api.service';
import { normalizeError } from '../utils/normalize-error';
import { elapsedSecondsLog } from '../utils/timing.util';
import { ContentSyncService } from './content-sync.service';
import { PermissionsSyncService } from './permissions-sync.service';

@Injectable()
export class SharepointSynchronizationService {
  private readonly logger = new Logger(this.constructor.name);
  private isScanning = false;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly graphApiService: GraphApiService,
    private readonly contentSyncService: ContentSyncService,
    private readonly permissionsSyncService: PermissionsSyncService,
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

    this.logger.log(`Starting scan of ${siteIdsToScan.length} SharePoint sites...`);

    for (const siteId of siteIdsToScan) {
      const logPrefix = `[SiteId: ${siteId}] `;

      const siteStartTime = Date.now();
      const items = await this.graphApiService.getAllSiteItems(siteId);
      this.logger.log(`${logPrefix} Finished scanning in ${elapsedSecondsLog(siteStartTime)}`);

      if (items.length === 0) {
        this.logger.warn(`${logPrefix} Found no items marked for synchronization.`);
        continue;
      }

      try {
        await this.contentSyncService.syncContentForSite(siteId, items);
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
}
