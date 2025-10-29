import { randomUUID } from 'node:crypto';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { DEFAULT_MIME_TYPE } from '../constants/defaults.constants';
import type { SharepointContentItem } from '../msgraph/types/sharepoint-content-item.interface';
import { normalizeError } from '../utils/normalize-error';
import { getItemUrl } from '../utils/sharepoint.util';
import { AspxProcessingStep } from './steps/aspx-processing.step';
import { ContentFetchingStep } from './steps/content-fetching.step';
import { ContentRegistrationStep } from './steps/content-registration.step';
import { IngestionFinalizationStep } from './steps/ingestion-finalization.step';
import type { IPipelineStep } from './steps/pipeline-step.interface';
import { StorageUploadStep } from './steps/storage-upload.step';
import type { PipelineResult, ProcessingContext } from './types/processing-context';

@Injectable()
export class ProcessingPipelineService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly pipelineSteps: IPipelineStep[];
  private readonly stepTimeoutMs: number;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly contentFetchingStep: ContentFetchingStep,
    private readonly aspxProcessingStep: AspxProcessingStep,
    private readonly contentRegistrationStep: ContentRegistrationStep,
    private readonly storageUploadStep: StorageUploadStep,
    private readonly ingestionFinalizationStep: IngestionFinalizationStep,
  ) {
    this.pipelineSteps = [
      this.contentFetchingStep,
      this.aspxProcessingStep,
      this.contentRegistrationStep,
      this.storageUploadStep,
      this.ingestionFinalizationStep,
    ];
    this.stepTimeoutMs =
      this.configService.get('processing.stepTimeoutSeconds', { infer: true }) * 1000;
  }

  public async processItem(pipelineItem: SharepointContentItem): Promise<PipelineResult> {
    const startTime = new Date();
    const correlationId = randomUUID();
    const rootScopeName = this.configService.get('unique.rootScopeName', { infer: true });

    const context: ProcessingContext = {
      correlationId,
      pipelineItem,
      startTime,
      knowledgeBaseUrl: getItemUrl(pipelineItem, rootScopeName),
      mimeType: this.resolveMimeType(pipelineItem),
    };

    this.logger.log(
      `[${correlationId}] Starting processing pipeline for item: ${pipelineItem.item.id}`,
    );

    for (const step of this.pipelineSteps) {
      try {
        await Promise.race([step.execute(context), this.timeoutPromise(step)]);

        this.logger.debug(`[${correlationId}] Completed step: ${step.stepName}`);
        if (step.cleanup) await step.cleanup(context);
      } catch (error) {
        const totalDuration = Date.now() - startTime.getTime();
        const normalizedError = normalizeError(error);
        this.logger.error(
          `[${correlationId}] Pipeline failed at step: ${step.stepName} after ${totalDuration}ms: ${normalizedError.message}`,
        );

        if (step.cleanup) await step.cleanup(context);
        this.finalCleanup(context);

        return { success: false };
      }
    }

    this.finalCleanup(context);
    const totalDuration = Date.now() - startTime.getTime();
    this.logger.log(
      `[${correlationId}] Pipeline completed successfully in ${totalDuration}ms for file id:${pipelineItem.item.id}`,
    );

    return { success: true };
  }

  private resolveMimeType(pipelineItem: SharepointContentItem): string {
    const isDriveItem = pipelineItem.itemType === 'driveItem';
    const mimeType = isDriveItem ? pipelineItem.item.file?.mimeType : undefined;
    return mimeType ?? DEFAULT_MIME_TYPE;
  }

  private timeoutPromise(step: IPipelineStep) {
    const timeoutError = new Error(`Step ${step.stepName} timed out after ${this.stepTimeoutMs}ms`);
    return new Promise((_resolve, reject) => {
      setTimeout(() => reject(timeoutError), this.stepTimeoutMs);
    });
  }

  private finalCleanup(context: ProcessingContext) {
    if (context.contentBuffer) {
      context.contentBuffer = undefined;
      delete context.contentBuffer;
    }
  }
}
