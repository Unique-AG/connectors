import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import pLimit from 'p-limit';
import { Config } from '../config';
import { IngestionMode } from '../constants/ingestion.constants';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { ScopeManagementService, type ScopePathToIdMap } from '../sharepoint-synchronization/scope-management.service';
import { ProcessingPipelineService } from './processing-pipeline.service';

@Injectable()
export class ItemProcessingOrchestratorService {
  private readonly logger = new Logger(ItemProcessingOrchestratorService.name);

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly processingPipelineService: ProcessingPipelineService,
    private readonly scopeManagementService: ScopeManagementService,
  ) {}

  public async processItems(
    siteId: string,
    items: SharepointContentItem[],
    scopePathToIdMap?: ScopePathToIdMap,
  ): Promise<void> {
    const concurrency = this.configService.get('processing.concurrency', { infer: true });
    const limit = pLimit(concurrency);

    if (items.length === 0) {
      this.logger.log(`No items to process for site ${siteId}`);
      return;
    }

    this.logger.log(`Processing ${items.length} items for site ${siteId}`);

    const ingestionMode = this.configService.get('unique.ingestionMode', { infer: true });
    const configuredScopeId = this.configService.get('unique.scopeId', { infer: true });
    const itemIdToScopeIdMap =
      ingestionMode === IngestionMode.Recursive
        ? this.scopeManagementService.buildItemIdToScopeIdMap(items, scopePathToIdMap)
        : undefined;

    const results = await Promise.allSettled(
      items.map((item) =>
        limit(async () => {
          const scopeId =
            ingestionMode === IngestionMode.Recursive
              ? itemIdToScopeIdMap?.get(item.item.id)
              : configuredScopeId;

          assert(scopeId, `Failed to resolve scope ID for item ${item.item.id}`);
          await this.processingPipelineService.processItem(item, scopeId);
        }),
      ),
    );

    const rejected = results.filter((result) => result.status === 'rejected');
    if (rejected.length > 0) {
      this.logger.warn(`Completed processing with ${rejected.length} failures for site ${siteId}`);
    }
  }
}
