import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import pLimit from 'p-limit';
import { DEFAULT_PROCESSING_CONCURRENCY } from '../constants/defaults.constants';
import type { DriveItem } from '../types/sharepoint.types';
import type { FileDiffResponse } from '../unique-api/types/unique-api.types';
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
    files: DriveItem[],
    diffResult: FileDiffResponse,
  ): Promise<void> {
    const concurrency = this.configService.get<number>(
      'pipeline.processingConcurrency',
      DEFAULT_PROCESSING_CONCURRENCY,
    );

    const newFileKeys = new Set(diffResult.newAndUpdatedFiles);
    const siteFiles = files.filter(
      (file) => file.parentReference?.siteId === siteId && newFileKeys.has(`sharepoint_file_${file.id}`),
    );
    if (siteFiles.length === 0) {
      this.logger.debug(`No files to process for site ${siteId}`);
      return;
    }

    this.logger.log(
      `Processing ${siteFiles.length} files for site ${siteId} with concurrency=${concurrency}`,
    );

    const limit = pLimit(concurrency);
    const results = await Promise.allSettled(
      siteFiles.map((file) =>
        limit(async () => {
          await this.processingPipelineService.processFile(file);
        }),
      ),
    );

    const rejected = results.filter((r) => r.status === 'rejected');
    if (rejected.length > 0) {
      this.logger.warn(
        `Completed processing with ${rejected.length} failures for site ${siteId}`,
      );
    }
  }
}
