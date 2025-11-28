import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { request } from 'undici';
import { Config } from '../../config';
import { HTTP_STATUS_OK_MAX } from '../../constants/defaults.constants';
import { redact, shouldConcealLogs, smear } from '../../utils/logging.util';
import { normalizeError } from '../../utils/normalize-error';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class StorageUploadStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.StorageUpload;
  private readonly shouldConcealLogs: boolean;

  public constructor(private readonly configService: ConfigService<Config, true>) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();

    this.logger.debug(
      `[${context.correlationId}] Starting storage upload for file: ${context.pipelineItem.item.id}`,
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
      delete context.contentBuffer;
      this.logger.debug(`[${context.correlationId}] Released content buffer memory`);
    }
  }

  private async performUpload(context: ProcessingContext): Promise<void> {
    assert.ok(context.contentBuffer, 'Content buffer not found - content fetching may have failed');
    assert.ok(context.uploadUrl, 'Upload URL not found - content registration may have failed');

    this.logger.debug({
      msg: 'performUpload details:',
      correlationId: context.correlationId,
      fileId: context.pipelineItem.item.id,
      driveId: context.pipelineItem.driveId,
      siteId: this.shouldConcealLogs
        ? smear(context.pipelineItem.siteId)
        : context.pipelineItem.siteId,
      uploadUrl: this.shouldConcealLogs ? redact(context.uploadUrl) : context.uploadUrl,
      mimeType: context.mimeType,
    });

    const mimeType = context.mimeType;
    try {
      const response = await request(context.uploadUrl, {
        method: 'PUT',
        headers: { 'Content-Type': mimeType, 'x-ms-blob-type': 'BlockBlob' },
        body: context.contentBuffer,
      });

      if (response.statusCode < 200 || response.statusCode >= HTTP_STATUS_OK_MAX) {
        const responseBody = await response.body.text().catch(() => 'Unable to read response body');
        throw new Error(
          `Upload failed with status ${response.statusCode}. Response: ${responseBody}`,
        );
      }

      this.logger.debug(`[${context.correlationId}] Upload completed successfully`);
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] Upload failed: ${message}`);
      throw error;
    }
  }
}
