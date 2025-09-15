import { Injectable, Logger } from '@nestjs/common';
import { request } from 'undici';
import { DEFAULT_MIME_TYPE, HTTP_STATUS_OK_MAX } from '../constants/defaults.constants';
import type { IPipelineStep } from './steps/pipeline-step.interface';
import type { ProcessingContext } from './types/processing-context';
import { PipelineStep } from './types/processing-context';

@Injectable()
export class StorageUploadStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.STORAGE_UPLOAD;

  public constructor() {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();
    try {
      this.logger.debug(
        `[${context.correlationId}] Starting storage upload for file: ${context.fileName}`,
      );
      if (!context.contentBuffer) {
        throw new Error('Content buffer not found - content fetching may have failed');
      }
      if (!context.uploadUrl) {
        throw new Error('Upload URL not found - content registration may have failed');
      }
      const fileSizeBytes = context.contentBuffer.length;
      const fileSizeKB = Math.round(fileSizeBytes / 1024);
      this.logger.debug(
        `[${context.correlationId}] Uploading ${fileSizeKB}KB to storage: ${context.uploadUrl}`,
      );
      await this.performUpload(context);
      const _stepDuration = Date.now() - stepStartTime;
      return context;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
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
    const uploadUrl = context.uploadUrl ?? '';
    const contentBuffer = context.contentBuffer ?? Buffer.alloc(0);
    const mimeType = context.metadata.mimeType ?? DEFAULT_MIME_TYPE;
    try {
      const response = await request(uploadUrl, {
        method: 'PUT',
        headers: {
          'Content-Type': mimeType,
          'x-ms-blob-type': 'BlockBlob',
        },
        body: contentBuffer,
        throwOnError: true,
      });
      if (response.statusCode < 200 || response.statusCode >= HTTP_STATUS_OK_MAX) {
        throw new Error(`Upload failed with status ${response.statusCode}`);
      }
      this.logger.debug(`[${context.correlationId}] Upload completed successfully`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.logger.error(`[${context.correlationId}] Upload failed: ${message}`);
      throw error;
    }
  }
}
