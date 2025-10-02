import { randomUUID } from 'node:crypto';
import type { FieldValueSet } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
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
    private readonly configService: ConfigService,
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
      (this.configService.get<number>('pipeline.stepTimeoutSeconds') as number) * 1000;
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
    let currentStep = <IPipelineStep>this.fileProcessingSteps[0];
    try {
      for (const step of this.fileProcessingSteps) {
        currentStep = step;
        await this.executeStepWithTimeout(step, context);

        this.logger.debug(`[${correlationId}] Completed step: ${step.stepName}`);

        if (currentStep.cleanup) await currentStep.cleanup(context);
      }

      const totalDuration = Date.now() - startTime.getTime();
      this.logger.log(
        `[${correlationId}] Pipeline completed successfully in ${totalDuration}ms for file name: ${file.name} file id:${file.id}`,
      );

      return { success: true };
    } catch (error) {
      const totalDuration = Date.now() - startTime.getTime();
      this.logger.error(
        `[${correlationId}] Pipeline failed at step: ${currentStep.stepName} after ${totalDuration}ms`,
        error instanceof Error ? error.stack : String(error),
      );

      if (currentStep.cleanup) await currentStep.cleanup(context);

      this.finalCleanup(context);
      return { success: false };
    }
  }

  private async executeStepWithTimeout(
    step: IPipelineStep,
    context: ProcessingContext,
  ): Promise<void> {
    try {
      await Promise.race([step.execute(context), this.timeoutPromise(step)]);
    } catch (error) {
      this.logger.error(
        `[${context.correlationId}] Step ${String(step.stepName)} failed: ${String(
          (error as Error).message,
        )}`,
      );
      throw error;
    }
  }

  private timeoutPromise(step: IPipelineStep) {
    return new Promise((_resolve, reject) => {
      setTimeout(
        () =>
          reject(
            new Error(
              `Step ${String(step.stepName)} timed out after ${String(this.stepTimeoutMs)}ms`,
            ),
          ),
        this.stepTimeoutMs,
      );
    });
  }

  private finalCleanup(context: ProcessingContext) {
    try {
      if (context.contentBuffer) {
        context.contentBuffer = undefined;
        this.logger.log(`[${context.correlationId}] Released remaining content buffer memory`);
      }
      context.metadata = {} as never;
    } catch (cleanupError) {
      this.logger.error(`[${context.correlationId}] Final cleanup failed:`, cleanupError as Error);
    }
  }
}
