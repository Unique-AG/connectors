import assert from 'node:assert';
import { Readable } from 'node:stream';
import { Injectable, Logger } from '@nestjs/common';
import { TenantConfigLoaderService } from '../../config/tenant-config-loader.service';
import { HTTP_STATUS_OK_MAX } from '../../constants/defaults.constants';
import { GraphApiService } from '../../microsoft-apis/graph/graph-api.service';
import { DriveItem } from '../../microsoft-apis/graph/types/sharepoint.types';
import { HttpClientService } from '../../shared/services/http-client.service';
import { UniqueFilesService } from '../../unique-api/unique-files/unique-files.service';
import { redact, shouldConcealLogs, smear } from '../../utils/logging.util';
import { sanitizeError } from '../../utils/normalize-error';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class UploadContentStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.UploadContent;
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly tenantConfigLoaderService: TenantConfigLoaderService,
    private readonly httpClientService: HttpClientService,
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly apiService: GraphApiService,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.tenantConfigLoaderService);
  }

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();
    const logPrefix = `[CorrelationId: ${context.correlationId}]`;

    this.logger.debug(
      `${logPrefix} Starting streaming upload for item: ${context.pipelineItem.item.id}`,
    );

    try {
      if (context.pipelineItem.itemType === 'listItem') {
        await this.uploadListItemContent(context);
      } else {
        await this.uploadDriveItemContent(context, context.pipelineItem.item);
      }

      context.uploadSucceeded = true;
      const stepDuration = Date.now() - stepStartTime;
      this.logger.debug(`${logPrefix} Streaming upload completed in ${stepDuration}ms`);

      return context;
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Streaming upload failed`,
        correlationId: context.correlationId,
        itemId: context.pipelineItem.item.id,
        driveId: context.pipelineItem.driveId,
        siteId: this.shouldConcealLogs
          ? smear(context.pipelineItem.siteId)
          : context.pipelineItem.siteId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  public async cleanup(context: ProcessingContext): Promise<void> {
    const logPrefix = `[CorrelationId: ${context.correlationId}, Site: ${this.shouldConcealLogs ? smear(context.pipelineItem.siteId) : context.pipelineItem.siteId}]`;

    if (!context.uploadSucceeded && context.uniqueContentId) {
      try {
        await this.uniqueFilesService.deleteFile(context.uniqueContentId);
        this.logger.warn({
          msg: `${logPrefix} Removed registered content after failed upload`,
          correlationId: context.correlationId,
          contentId: context.uniqueContentId,
        });
      } catch (error) {
        this.logger.error({
          msg: `${logPrefix} Failed to delete registered content after upload failure`,
          correlationId: context.correlationId,
          contentId: context.uniqueContentId,
          error: sanitizeError(error),
        });
      }
    }

    if (context.htmlContent) {
      context.htmlContent = undefined;
      delete context.htmlContent;
      this.logger.debug(`${logPrefix} Released HTML content memory`);
    }
  }

  private async uploadListItemContent(context: ProcessingContext): Promise<void> {
    assert.ok(context.htmlContent, 'HTML content not found - ASPX processing may have failed');
    assert.ok(context.uploadUrl, 'Upload URL not found - content registration may have failed');

    const contentStream = Readable.from(Buffer.from(context.htmlContent, 'utf-8'));
    await this.streamUpload(context, contentStream);
  }

  private async uploadDriveItemContent(context: ProcessingContext, item: DriveItem): Promise<void> {
    this.validateMimeType(item);
    assert.ok(context.uploadUrl, 'Upload URL not found - content registration may have failed');

    const contentStream = await this.apiService.getFileContentStream(
      context.pipelineItem.driveId,
      context.pipelineItem.item.id,
    );

    await this.streamUpload(context, contentStream);
  }

  private async streamUpload(context: ProcessingContext, stream: Readable): Promise<void> {
    const logPrefix = `[CorrelationId: ${context.correlationId}]`;
    assert.ok(context.uploadUrl, 'Upload URL not found');

    this.logger.debug({
      msg: 'streamUpload details:',
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
    const contentLength =
      context.pipelineItem.itemType === 'listItem'
        ? context.fileSize
        : context.pipelineItem.item.size;

    const headers: Record<string, string> = {
      'Content-Type': mimeType ?? 'application/octet-stream',
      'Content-Length': String(contentLength),
      'x-ms-blob-type': 'BlockBlob',
    };

    try {
      const response = await this.httpClientService.request(context.uploadUrl, {
        method: 'PUT',
        headers,
        body: stream,
      });

      if (response.statusCode < 200 || response.statusCode >= HTTP_STATUS_OK_MAX) {
        const responseBody = await response.body.text().catch(() => 'Unable to read response body');
        throw new Error(
          `Upload failed with status ${response.statusCode}. Response: ${responseBody}`,
        );
      }

      this.logger.debug(`${logPrefix} Stream upload completed successfully`);
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Stream upload failed`,
        correlationId: context.correlationId,
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  private validateMimeType(item: DriveItem): void {
    const tenantConfig = this.tenantConfigLoaderService.loadTenantConfig();
    const allowedMimeTypes = tenantConfig.processingAllowedMimeTypes;
    assert.ok(item.file?.mimeType, `MIME type is missing for this item. Skipping download.`);
    assert.ok(
      allowedMimeTypes?.includes(item.file.mimeType),
      `MIME type ${item.file.mimeType} is not allowed. Skipping download.`,
    );
  }
}
