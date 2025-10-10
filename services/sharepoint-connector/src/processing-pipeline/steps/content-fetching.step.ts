import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { GraphApiService } from '../../msgraph/graph-api.service';
import { normalizeError } from '../../utils/normalize-error';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class ContentFetchingStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.ContentFetching;

  public constructor(
    private readonly apiService: GraphApiService,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();
    this.validateMimeType(context.metadata.mimeType, context.correlationId);

    try {
      const contentBuffer = await this.apiService.downloadFileContent(
        context.metadata.driveId,
        context.fileId,
      );

      context.contentBuffer = contentBuffer;
      context.fileSize = contentBuffer.length;

      const _stepDuration = Date.now() - stepStartTime;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] Content fetching failed: ${message}`);
      throw error;
    }
  }

  private validateMimeType(mimeType: string | undefined, correlationId: string): void {
    const allowedMimeTypes = this.configService.get('processing.allowedMimeTypes', { infer: true });
    assert.ok(
      mimeType,
      `MIME type is missing for this item. Skipping download. [${correlationId}]`,
    );
    assert.ok(
      allowedMimeTypes.includes(mimeType),
      `MIME type ${mimeType} is not allowed. Skipping download.}`,
    );
  }
}
