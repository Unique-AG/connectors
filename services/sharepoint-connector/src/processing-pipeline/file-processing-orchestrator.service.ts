import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import pLimit from 'p-limit';
import type { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';
import type { FileDiffResponse } from '../unique-api/unique-api.types';
import { ProcessingPipelineService } from './processing-pipeline.service';

@Injectable()
export class FileProcessingOrchestratorService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService,
    private readonly processingPipelineService: ProcessingPipelineService,
  ) {}

  public async processFilesForSite(
    siteId: string,
    files: EnrichedDriveItem[],
    diffResult: FileDiffResponse,
  ): Promise<void> {
    const concurrency = this.configService.get<number>('pipeline.processingConcurrency') as number;

    const newFileKeys = new Set(diffResult.newAndUpdatedFiles);
    const filesToProcess = files.filter((file) => newFileKeys.has(`sharepoint_file_${file.id}`));
    if (filesToProcess.length === 0) {
      this.logger.debug(`No files to process for site ${siteId}`);
      return;
    }

    this.logger.log(
      `Processing ${filesToProcess.length} files for site ${siteId} with concurrency=${concurrency}`,
    );

    const limit = pLimit(concurrency);
    const results = await Promise.allSettled(
      filesToProcess.map((file) =>
        limit(async () => {
          await this.processingPipelineService.processFile(file);
        }),
      ),
    );

    const rejected = results.filter((result) => result.status === 'rejected');
    if (rejected.length > 0) {
      this.logger.warn(`Completed processing with ${rejected.length} failures for site ${siteId}`);
    }
  }
}
