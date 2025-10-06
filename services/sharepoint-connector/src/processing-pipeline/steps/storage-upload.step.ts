import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { request } from 'undici';
import { HTTP_STATUS_OK_MAX } from '../../constants/defaults.constants';
import { normalizeError } from '../../utils/normalize-error';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class StorageUploadStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.StorageUpload;

  public constructor() {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();
    assert.ok(context.contentBuffer, 'Content buffer not found - content fetching may have failed');
    assert.ok(context.uploadUrl, 'Upload URL not found - content registration may have failed');

    this.logger.debug(
      `[${context.correlationId}] Starting storage upload for file: ${context.fileName}`,
    );

    try {
      await this.performUpload(context);
      const _stepDuration = Date.now() - stepStartTime;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] Storage upload failed: ${message}`);
      throw error;
    }
  }

  public async cleanup(context: ProcessingContext): Promise<void> {
    if (context.contentBuffer) {
      context.contentBuffer = undefined;
      this.logger.debug(`[${context.correlationId}] Released content buffer memory`);
    }
  }

  private async performUpload(context: ProcessingContext): Promise<void> {
    const uploadUrl = context.uploadUrl as string;
    const contentBuffer = context.contentBuffer as Buffer;
    const mimeType = context.metadata.mimeType;

    try {
      const response = await request(uploadUrl, {
        method: 'PUT',
        headers: { 'Content-Type': mimeType, 'x-ms-blob-type': 'BlockBlob' },
        body: contentBuffer,
      });

      if (response.statusCode < 200 || response.statusCode >= HTTP_STATUS_OK_MAX) {
        throw new Error(`Upload failed with status ${response.statusCode}`);
      }

      this.logger.debug(`[${context.correlationId}] Upload completed successfully`);
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] Upload failed: ${message}`);
      throw error;
    }
  }
}
