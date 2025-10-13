import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import pLimit from 'p-limit';
import { Config } from '../config';
import type { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';
import { buildSharepointFileKey } from '../shared/sharepoint-key.util';
import type { FileDiffResponse } from '../unique-api/unique-api.types';
import { ProcessingPipelineService } from './processing-pipeline.service';

@Injectable()
export class FileProcessingOrchestratorService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly processingPipelineService: ProcessingPipelineService,
  ) {}

  public async processFilesForSite(
    siteId: string,
    files: EnrichedDriveItem[],
    diffResult: FileDiffResponse,
  ): Promise<void> {
    const concurrency = this.configService.get('processing.concurrency', { infer: true });
    const scopeId = this.configService.get('unique.scopeId', { infer: true });
    const limit = pLimit(concurrency);

    const newFileKeys = new Set(diffResult.newAndUpdatedFiles);
    const filesToProcess = files.filter((file) => {
      const fileKey = buildSharepointFileKey({
        scopeId,
        siteId: file.siteId,
        driveName: file.driveName,
        folderPath: file.folderPath,
        fileId: file.id,
        fileName: file.name,
      });
      return newFileKeys.has(fileKey);
    });

    if (filesToProcess.length === 0) {
      this.logger.log(`No files to process for site ${siteId}`);
      return;
    }

    this.logger.log(`Processing ${filesToProcess.length} files for site ${siteId}`);

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
