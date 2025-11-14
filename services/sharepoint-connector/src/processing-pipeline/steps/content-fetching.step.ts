import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { GraphApiService } from '../../microsoft-apis/graph/graph-api.service';
import { DriveItem } from '../../microsoft-apis/graph/types/sharepoint.types';
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
    if (context.pipelineItem.itemType === 'listItem') {
      return await this.fetchListItemContent(context);
    }

    if (context.pipelineItem.itemType === 'driveItem') {
      return await this.fetchFileContent(context, context.pipelineItem.item);
    }

    assert.fail('Invalid pipeline item type');
  }

  private async fetchListItemContent(context: ProcessingContext): Promise<ProcessingContext> {
    try {
      const { canvasContent, wikiField } = await this.apiService.getAspxPageContent(
        context.pipelineItem.siteId,
        context.pipelineItem.driveId,
        context.pipelineItem.item.id,
      );

      const content = canvasContent || wikiField || '';
      context.contentBuffer = Buffer.from(content, 'utf-8');
      // Use content buffer length for list items
      context.fileSize = context.contentBuffer.length;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error({
        msg: 'Site page content fetching failed',
        correlationId: context.correlationId,
        itemId: context.pipelineItem.item.id,
        driveId: context.pipelineItem.driveId,
        siteId: context.pipelineItem.siteId,
        error: message,
      });
      throw error;
    }
  }

  private async fetchFileContent(
    context: ProcessingContext,
    item: DriveItem,
  ): Promise<ProcessingContext> {
    this.validateMimeType(item);

    try {
      const contentBuffer = await this.apiService.downloadFileContent(
        context.pipelineItem.driveId,
        context.pipelineItem.item.id,
      );

      context.contentBuffer = contentBuffer;
      context.fileSize = item.size;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error({
        msg: 'Content fetching failed',
        correlationId: context.correlationId,
        itemId: context.pipelineItem.item.id,
        driveId: context.pipelineItem.driveId,
        siteId: context.pipelineItem.siteId,
        error: message,
      });
      throw error;
    }
  }

  private validateMimeType(item: DriveItem): void {
    const allowedMimeTypes = this.configService.get('processing.allowedMimeTypes', { infer: true });
    assert.ok(item.file?.mimeType, `MIME type is missing for this item. Skipping download.`);
    assert.ok(
      allowedMimeTypes.includes(item.file.mimeType),
      `MIME type ${item.file.mimeType} is not allowed. Skipping download.`,
    );
  }
}
