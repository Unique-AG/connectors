import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import pLimit from 'p-limit';
import { Config } from '../config';
import { IngestionMode } from '../constants/ingestion.constants';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { ScopeManagementService } from '../sharepoint-synchronization/scope-management.service';
import type { FileDiffResponse } from '../unique-api/unique-api.types';
import { buildFileDiffKey } from '../utils/sharepoint.util';
import { ProcessingPipelineService } from './processing-pipeline.service';

@Injectable()
export class FileProcessingOrchestratorService {
  private readonly logger = new Logger(FileProcessingOrchestratorService.name);

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly processingPipelineService: ProcessingPipelineService,
    private readonly scopeManagementService: ScopeManagementService,
  ) {}

  public async processSiteItems(
    siteId: string,
    items: SharepointContentItem[],
    diffResult: FileDiffResponse,
    scopeCache?: Map<string, string>,
  ): Promise<void> {
    const concurrency = this.configService.get('processing.concurrency', { infer: true });
    const limit = pLimit(concurrency);
    const ingestionMode = this.configService.get('unique.ingestionMode', { infer: true });
    const ingestionScopeLocation = this.configService.get('unique.ingestionScopeLocation', { infer: true });

    const newFileKeys = new Set(diffResult.newAndUpdatedFiles);
    const filteredItems = items.filter((item) => {
      const key = buildFileDiffKey(item);
      return newFileKeys.has(key);
    });
    if (filteredItems.length === 0) {
      this.logger.log(`No files to process for site ${siteId}`);
      return;
    }

    this.logger.log(`Processing ${filteredItems.length} files for site ${siteId}`);

    // Build item scope ID map for recursive-advanced mode
    const itemScopeIdMap = ingestionMode === IngestionMode.RecursiveAdvanced
      ? this.scopeManagementService.buildItemScopeIdMap(
          filteredItems,
          ingestionScopeLocation,
          scopeCache,
        )
      : undefined;

    const results = await Promise.allSettled(
      filteredItems.map((item) =>
        limit(async () => {
          const itemScopeId = itemScopeIdMap?.get(item.item.id);
          await this.processingPipelineService.processItem(item, itemScopeId);
        }),
      ),
    );

    const rejected = results.filter((result) => result.status === 'rejected');
    if (rejected.length > 0) {
      this.logger.warn(`Completed processing with ${rejected.length} failures for site ${siteId}`);
    }
  }
}
