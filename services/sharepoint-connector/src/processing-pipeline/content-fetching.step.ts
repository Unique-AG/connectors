import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { SharepointApiService } from '../sharepoint-api/sharepoint-api.service';
import type { IPipelineStep } from './steps/pipeline-step.interface';
import type { ProcessingContext } from './types/processing-context';
import { PipelineStep } from './types/processing-context';

@Injectable()
export class ContentFetchingStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.CONTENT_FETCHING;

  public constructor(
    private readonly sharepointApiService: SharepointApiService,
    private readonly configService: ConfigService,
  ) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();
    try {
      this.logger.debug(
        `[${context.correlationId}] Starting content fetching for file: ${context.fileName}`,
      );
      const driveId = this.extractDriveId(context);
      const itemId = context.fileId;
      if (!driveId) {
        throw new Error('Drive ID not found in file metadata');
      }
      this.validateMimeType(
        (context.metadata as Record<string, unknown>).mimeType as string | undefined,
        context.correlationId,
      );
      const contentBuffer = await this.sharepointApiService.downloadFileContent(driveId, itemId);
      context.contentBuffer = contentBuffer;
      context.fileSize = contentBuffer.length;
      this.logger.debug(
        `[${context.correlationId}] Content fetching completed for file: ${context.fileName} (${String(
          Math.round(contentBuffer.length / 1024 / 1024),
        )}MB)`,
      );
      const _stepDuration = Date.now() - stepStartTime;
      return context;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.logger.error(`[${context.correlationId}] Content fetching failed: ${message}`);
      throw error;
    }
  }

  private extractDriveId(context: ProcessingContext): string | null {
    type ParentRef = { driveId?: string };
    type MetaShape = {
      driveId?: string;
      parentReference?: ParentRef;
      listItem?: { fields?: { driveId?: string } };
    };
    const metadata = context.metadata as MetaShape;
    if (typeof metadata.driveId === 'string' && metadata.driveId) return metadata.driveId;
    if (metadata.parentReference && typeof metadata.parentReference.driveId === 'string') {
      return metadata.parentReference.driveId;
    }
    if (metadata.listItem?.fields && typeof metadata.listItem.fields.driveId === 'string') {
      return metadata.listItem.fields.driveId;
    }
    this.logger.warn(
      `[${context.correlationId}] Drive ID not found in metadata. Available keys: ${Object.keys(
        metadata as Record<string, unknown>,
      ).join(', ')}`,
    );
    return null;
  }

  private validateMimeType(mimeType: string | undefined, correlationId: string): void {
    const allowedMimeTypes = this.configService.get<string[]>('sharepoint.allowedMimeTypes') ?? [];
    if (!mimeType) {
      throw new Error(`MIME type is missing for this item. Skipping download. [${correlationId}]`);
    }
    if (allowedMimeTypes.length > 0 && !allowedMimeTypes.includes(mimeType)) {
      throw new Error(
        `MIME type ${mimeType} is not allowed. Allowed types: ${allowedMimeTypes.join(', ')}`,
      );
    }
  }

  public async cleanup(context: ProcessingContext): Promise<void> {
    this.logger.debug(
      `[${context.correlationId}] Content fetching cleanup completed (buffer preserved for next steps)`,
    );
  }
}
