import { randomUUID } from 'node:crypto';
import type { FieldValueSet } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import type { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';
import { ContentFetchingStep } from './steps/content-fetching.step';
import { ContentRegistrationStep } from './steps/content-registration.step';
import { IngestionFinalizationStep } from './steps/ingestion-finalization.step';
import type { IPipelineStep } from './steps/pipeline-step.interface';
import { StorageUploadStep } from './steps/storage-upload.step';
import type { PipelineResult, ProcessingContext } from './types/processing-context';

@Injectable()
export class ProcessingPipelineService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly fileProcessingSteps: IPipelineStep[];
  private readonly stepTimeoutMs: number;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly contentFetchingStep: ContentFetchingStep,
    private readonly contentRegistrationStep: ContentRegistrationStep,
    private readonly storageUploadStep: StorageUploadStep,
    private readonly ingestionFinalizationStep: IngestionFinalizationStep,
  ) {
    this.fileProcessingSteps = [
      this.contentFetchingStep,
      this.contentRegistrationStep,
      this.storageUploadStep,
      this.ingestionFinalizationStep,
    ];
    this.stepTimeoutMs =
      this.configService.get('pipeline.stepTimeoutSeconds', { infer: true }) * 1000;
  }

  public async processFile(file: EnrichedDriveItem): Promise<PipelineResult> {
    const correlationId = randomUUID();
    const startTime = new Date();
    const context: ProcessingContext = {
      correlationId,
      fileId: file.id,
      fileName: file.name,
      fileSize: file.size,
      siteUrl: file.siteWebUrl,
      libraryName: file.driveId,
      downloadUrl: file.webUrl,
      startTime,
      metadata: {
        mimeType: file.file?.mimeType ?? undefined,
        isFolder: Boolean(file.folder),
        listItemFields: file.listItem?.fields as Record<string, FieldValueSet>,
        driveId: file.driveId,
        siteId: file.siteId,
        driveName: file.driveName,
        folderPath: file.folderPath,
        lastModifiedDateTime: file.lastModifiedDateTime,
      },
    };

    this.logger.log(
      `[${correlationId}] Starting processing pipeline for file: ${file.name} (${file.id})`,
    );

    for (const step of this.fileProcessingSteps) {
      try {
        await Promise.race([step.execute(context), this.timeoutPromise(step)]);

        this.logger.debug(`[${correlationId}] Completed step: ${step.stepName}`);
        if (step.cleanup) await step.cleanup(context);
      } catch (error) {
        const totalDuration = Date.now() - startTime.getTime();
        this.logger.error(
          `[${correlationId}] Pipeline failed at step: ${step.stepName} after ${totalDuration}ms`,
          error instanceof Error ? error.stack : String(error),
        );

        if (step.cleanup) await step.cleanup(context);
        this.finalCleanup(context);

        return { success: false };
      }
    }

    this.finalCleanup(context);
    const totalDuration = Date.now() - startTime.getTime();
    this.logger.log(
      `[${correlationId}] Pipeline completed successfully in ${totalDuration}ms for file name: ${file.name} file id:${file.id}`,
    );

    return { success: true };
  }

  private timeoutPromise(step: IPipelineStep) {
    const timeoutError = new Error(`Step ${step.stepName} timed out after ${this.stepTimeoutMs}ms`);
    return new Promise((_resolve, reject) => {
      setTimeout(() => reject(timeoutError), this.stepTimeoutMs);
    });
  }

  private finalCleanup(context: ProcessingContext) {
    if (context.contentBuffer) context.contentBuffer = undefined;
    context.metadata = {} as never;
  }
}
