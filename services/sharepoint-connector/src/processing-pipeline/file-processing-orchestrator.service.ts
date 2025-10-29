import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import pLimit from 'p-limit';
import { Config } from '../config';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { FileDiffResponse } from '../unique-api/unique-api.types';
import { ProcessingPipelineService } from './processing-pipeline.service';

@Injectable()
export class FileProcessingOrchestratorService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly processingPipelineService: ProcessingPipelineService,
  ) {}

  public async processSiteItems(
    siteId: string,
    items: SharepointContentItem[],
    diffResult: FileDiffResponse,
  ): Promise<void> {
    const concurrency = this.configService.get('processing.concurrency', { infer: true });
    const limit = pLimit(concurrency);

    const newFileKeys = new Set(diffResult.newAndUpdatedFiles);
    const filteredItems = items.filter((file) => newFileKeys.has(file.item.id));
    if (filteredItems.length === 0) {
      this.logger.log(`No files to process for site ${siteId}`);
      return;
    }

    this.logger.log(`Processing ${filteredItems.length} files for site ${siteId}`);

    const results = await Promise.allSettled(
      filteredItems.map((item) =>
        limit(async () => {
          await this.processingPipelineService.processItem(item);
        }),
      ),
    );

    const rejected = results.filter((result) => result.status === 'rejected');
    if (rejected.length > 0) {
      this.logger.warn(`Completed processing with ${rejected.length} failures for site ${siteId}`);
    }
  }
}
