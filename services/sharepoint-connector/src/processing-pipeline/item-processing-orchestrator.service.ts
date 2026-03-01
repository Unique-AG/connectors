import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import pLimit from 'p-limit';
import { Config } from '../config';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { SharepointSyncContext } from '../sharepoint-synchronization/sharepoint-sync-context.interface';
import { ProcessingPipelineService } from './processing-pipeline.service';

@Injectable()
export class ItemProcessingOrchestratorService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly processingPipelineService: ProcessingPipelineService,
  ) {}

  public async processItems(
    syncContext: SharepointSyncContext,
    newItems: SharepointContentItem[],
    updatedItems: SharepointContentItem[],
    getScopeIdForItem: (item: SharepointContentItem) => string,
  ): Promise<void> {
    const concurrency = this.configService.get('processing.concurrency', { infer: true });
    const limit = pLimit(concurrency);
    const { siteId } = syncContext.siteConfig;
    const logPrefix = `[Site: ${siteId}]`;

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
        const scopeId = getScopeIdForItem(item);
        await this.processingPipelineService.processItem(item, scopeId, 'new', syncContext);
      }),
    );

    const updatedItemsPromises = updatedItems.map((item) =>
      limit(async () => {
        const scopeId = getScopeIdForItem(item);
        await this.processingPipelineService.processItem(item, scopeId, 'updated', syncContext);
      }),
    );

    const results = await Promise.allSettled([...updatedItemsPromises, ...newItemsPromises]);

    const rejected = results.filter((result) => result.status === 'rejected');
    if (rejected.length > 0) {
      this.logger.warn(`${logPrefix} Completed processing with ${rejected.length} failures`);
    }
  }
}
