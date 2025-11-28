import { randomUUID } from 'node:crypto';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Counter, ValueType } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import { toSnakeCase } from 'remeda';
import { Config } from '../config';
import { DEFAULT_MIME_TYPE } from '../constants/defaults.constants';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { SharepointSyncContext } from '../sharepoint-synchronization/types';
import { shouldConcealLogs, smear } from '../utils/logging.util';
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
  private readonly spcIngestionFileProcessedTotal: Counter;
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly contentFetchingStep: ContentFetchingStep,
    private readonly aspxProcessingStep: AspxProcessingStep,
    private readonly contentRegistrationStep: ContentRegistrationStep,
    private readonly storageUploadStep: StorageUploadStep,
    private readonly ingestionFinalizationStep: IngestionFinalizationStep,
    metricService: MetricService,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
    this.pipelineSteps = [
      this.contentFetchingStep,
      this.aspxProcessingStep,
      this.contentRegistrationStep,
      this.storageUploadStep,
      this.ingestionFinalizationStep,
    ];
    this.stepTimeoutMs =
      this.configService.get('processing.stepTimeoutSeconds', { infer: true }) * 1000;

    this.spcIngestionFileProcessedTotal = metricService.getCounter(
      'spc_ingestion_file_processed_total',
      {
        description: 'Number of files processed by ingestion pipeline steps',
        valueType: ValueType.INT,
      },
    );
  }

  public async processItem(
    pipelineItem: SharepointContentItem,
    scopeId: string,
    fileStatus: 'new' | 'updated',
    syncContext: SharepointSyncContext,
  ): Promise<PipelineResult> {
    const startTime = new Date();
    const correlationId = randomUUID();

    const context: ProcessingContext = {
      correlationId,
      pipelineItem,
      startTime,
      knowledgeBaseUrl: getItemUrl(pipelineItem),
      mimeType: this.resolveMimeType(pipelineItem),
      scopeId,
      fileStatus,
      syncContext,
    };

    const logSiteId = this.shouldConcealLogs ? smear(syncContext.siteId) : syncContext.siteId;
    const logPrefix = `[SiteId: ${logSiteId}][CorrelationId: ${correlationId}]`;
    this.logger.log(`${logPrefix} Starting processing pipeline for item: ${pipelineItem.item.id}`);

    for (const step of this.pipelineSteps) {
      try {
        await this.executeWithTimeout(step, context);

        this.spcIngestionFileProcessedTotal.add(1, {
          sp_site_id: logSiteId,
          step_name: toSnakeCase(step.stepName),
          file_state: fileStatus,
          result: 'success',
        });

        this.logger.debug(`${logPrefix} Completed step: ${step.stepName}`);
        if (step.cleanup) await step.cleanup(context);
      } catch (error) {
        const totalDuration = Date.now() - startTime.getTime();
        const normalizedError = normalizeError(error);
        const isTimeout = 'isTimeout' in normalizedError && Boolean(normalizedError.isTimeout);

        this.spcIngestionFileProcessedTotal.add(1, {
          sp_site_id: logSiteId,
          step_name: toSnakeCase(step.stepName),
          file_state: fileStatus,
          result: isTimeout ? 'timeout' : 'failure',
        });

        this.logger.error(
          `${logPrefix} Pipeline ${isTimeout ? 'timed out' : 'failed'} at step: ` +
            `${step.stepName} after ${totalDuration}ms: ${normalizedError.message}`,
        );

        if (step.cleanup) await step.cleanup(context);
        this.finalCleanup(context);

        return { success: false };
      }
    }

    this.finalCleanup(context);
    const totalDuration = Date.now() - startTime.getTime();
    this.logger.log(
      `${logPrefix} Pipeline completed successfully in ${totalDuration}ms for file id:${pipelineItem.item.id}`,
    );

    return { success: true };
  }

  private resolveMimeType(pipelineItem: SharepointContentItem): string {
    const isDriveItem = pipelineItem.itemType === 'driveItem';
    const mimeType = isDriveItem ? pipelineItem.item.file?.mimeType : undefined;
    return mimeType ?? DEFAULT_MIME_TYPE;
  }

  // Executes a pipeline step with a timeout. We use a custom Promise implementation instead of
  // Promise.race() to ensure the timeout is properly cleared when the step completes. With
  // Promise.race(), the timeout callback would remain scheduled even after successful completion,
  // potentially accumulating orphaned timeouts in high-throughput scenarios.
  private executeWithTimeout(
    step: IPipelineStep,
    context: ProcessingContext,
  ): Promise<ProcessingContext> {
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        const timeoutError = new Error(
          `Step ${step.stepName} timed out after ${this.stepTimeoutMs}ms`,
        ) as Error & { isTimeout: boolean };
        timeoutError.isTimeout = true;
        reject(timeoutError);
      }, this.stepTimeoutMs);

      step
        .execute(context)
        .then(resolve)
        .catch(reject)
        .finally(() => clearTimeout(timeoutId));
    });
  }

  private finalCleanup(context: ProcessingContext) {
    if (context.contentBuffer) {
      context.contentBuffer = undefined;
      delete context.contentBuffer;
    }
  }
}
