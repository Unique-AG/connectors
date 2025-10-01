import { randomUUID } from 'node:crypto';
import {DriveItem, FieldValueSet} from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
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

  public async processFile(file: DriveItem): Promise<PipelineResult> {
    const correlationId = randomUUID();
    const startTime = new Date();
    const context: ProcessingContext = {
      correlationId,
      fileId: file.id ?? '',
      fileName: file.name ?? '',
      fileSize: file.size ?? 0,
      siteUrl: file.parentReference?.siteId ?? '',
      libraryName: file.parentReference?.driveId ?? '',
      downloadUrl: file.webUrl ?? '',
      startTime,
      metadata: {
        mimeType: file.file?.mimeType ?? undefined,
        isFolder: Boolean(file.folder),
        listItemFields: (file.listItem?.fields as Record<string, FieldValueSet>),
        driveId: file.parentReference?.driveId ?? undefined,
        siteId: file.parentReference?.siteId ?? undefined,
        lastModifiedDateTime: file.lastModifiedDateTime ?? undefined,
      },
    };

    const completedSteps: string[] = [];
    let currentStepIndex = 0;

    try {
      this.logger.log(`[${correlationId}] Starting pipeline for file: ${file.name} (${file.id})`);
      for (let stepIndex = 0; stepIndex < this.fileProcessingSteps.length; stepIndex++) {
        currentStepIndex = stepIndex;
        const step = this.fileProcessingSteps[stepIndex];

        if (!step) continue;
        this.logger.debug(
          `[${correlationId}] Executing step ${stepIndex + 1}/${this.fileProcessingSteps.length}: ${step.stepName}`,
        );

        await this.executeStepWithTimeout(step, context);

        completedSteps.push(step.stepName);
        this.logger.debug(`[${correlationId}] Completed step: ${step.stepName}`);

        await this.cleanupStep(step, context);
      }

      const totalDuration = Date.now() - startTime.getTime();
      this.logger.log(
        `[${correlationId}] Pipeline completed successfully in ${totalDuration}ms for file: ${file.name}`,
      );

      await this.finalCleanup(context);
      return { success: true, context, completedSteps, totalDuration };
    } catch (error) {
      const totalDuration = Date.now() - startTime.getTime();
      this.logger.error(
        `[${correlationId}] Pipeline failed at step: ${this.fileProcessingSteps[currentStepIndex]?.stepName} after ${totalDuration}ms`,
        error instanceof Error ? error.stack : String(error),
      );

      const step = this.fileProcessingSteps[currentStepIndex];
      if (step?.cleanup) {
        await this.cleanupStep(step, context);
      }

      return { success: false, context, error: error as Error, completedSteps, totalDuration };
    }
  }

  private async executeStepWithTimeout(
    fileProcessingStep: IPipelineStep,
    context: ProcessingContext,
  ): Promise<void> {
    const timeoutPromise = new Promise((_resolve, _reject) => {
      setTimeout(() => {
        _reject(
          new Error(
            `Step ${String(fileProcessingStep.stepName)} timed out after ${String(this.stepTimeoutMs)}ms`,
          ),
        );
      }, this.stepTimeoutMs);
    });
    try {
      await Promise.race([fileProcessingStep.execute(context), timeoutPromise]);
    } catch (error) {
      this.logger.error(
        `[${context.correlationId}] Step ${String(fileProcessingStep.stepName)} failed: ${String(
          (error as Error).message,
        )}`,
      );
      throw error;
    }
  }

  private async cleanupStep(step: IPipelineStep, context: ProcessingContext): Promise<void> {
    try {
      if (step.cleanup) {
        this.logger.log(`[${context.correlationId}] Cleaning up step: ${step.stepName}`);
        await step.cleanup(context);
      }
    } catch (cleanupError) {
      this.logger.error(
        `[${context.correlationId}] Cleanup failed for step ${step.stepName}:`,
        cleanupError as Error,
      );
    }
  }

  private async finalCleanup(context: ProcessingContext): Promise<void> {
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
