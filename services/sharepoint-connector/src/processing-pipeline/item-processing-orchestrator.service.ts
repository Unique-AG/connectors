import { Injectable, Logger } from '@nestjs/common';
import pLimit from 'p-limit';
import type { SiteConfig } from '../config/tenant-config.schema';
import { TenantConfigLoaderService } from '../config/tenant-config-loader.service';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { SharepointSyncContext } from '../sharepoint-synchronization/types';
import { shouldConcealLogs, smear } from '../utils/logging.util';
import { ProcessingPipelineService } from './processing-pipeline.service';

@Injectable()
export class ItemProcessingOrchestratorService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly tenantConfigLoaderService: TenantConfigLoaderService,
    private readonly processingPipelineService: ProcessingPipelineService,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.tenantConfigLoaderService);
  }

  public async processItems(
    syncContext: SharepointSyncContext,
    newItems: SharepointContentItem[],
    updatedItems: SharepointContentItem[],
    getScopeIdForItem: (itemId: string) => string,
    siteConfig: SiteConfig,
  ): Promise<void> {
    const tenantConfig = this.tenantConfigLoaderService.loadTenantConfig();
    const concurrency = tenantConfig.processingConcurrency || 5; // Default concurrency
    const limit = pLimit(concurrency);
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(syncContext.siteId) : syncContext.siteId}]`;

    if (newItems.length === 0 && updatedItems.length === 0) {
      this.logger.log(`${logPrefix} No items to process`);
      return;
    }

    this.logger.log(
      `${logPrefix} Processing ${newItems.length + updatedItems.length} items ` +
        `(${newItems.length} new, ${updatedItems.length} updated)`,
    );

    const newItemsPromises = newItems.map((item) =>
      limit(async () => {
        const scopeId = getScopeIdForItem(item.item.id);
        await this.processingPipelineService.processItem(item, scopeId, 'new', syncContext, siteConfig);
      }),
    );

    const updatedItemsPromises = updatedItems.map((item) =>
      limit(async () => {
        const scopeId = getScopeIdForItem(item.item.id);
        await this.processingPipelineService.processItem(item, scopeId, 'updated', syncContext, siteConfig);
      }),
    );

    const results = await Promise.allSettled([...updatedItemsPromises, ...newItemsPromises]);

    const rejected = results.filter((result) => result.status === 'rejected');
    if (rejected.length > 0) {
      this.logger.warn(`${logPrefix} Completed processing with ${rejected.length} failures`);
    }
  }
}
