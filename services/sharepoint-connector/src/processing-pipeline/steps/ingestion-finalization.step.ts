import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '../../constants/ingestion.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { UniqueFileIngestionService } from '../../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import { shouldConcealLogs, smear } from '../../utils/logging.util';
import { normalizeError } from '../../utils/normalize-error';
import { buildIngestionItemKey } from '../../utils/sharepoint.util';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class IngestionFinalizationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.IngestionFinalization;
  private readonly sharepointBaseUrl: string;
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly uniqueFileIngestionService: UniqueFileIngestionService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();

    assert.ok(
      context.registrationResponse,
      `[${context.correlationId}] Ingestion finalization failed. Registration response not found in context - content registration may have failed`,
    );

    const fileKey = buildIngestionItemKey(context.pipelineItem);

    const ingestionFinalizationRequest = {
      key: fileKey,
      title: context.pipelineItem.fileName,
      mimeType: context.registrationResponse.mimeType,
      ownerType: context.registrationResponse.ownerType,
      byteSize: context.registrationResponse.byteSize,
      scopeId: context.scopeId,
      sourceOwnerType: UniqueOwnerType.Company,
      sourceName: INGESTION_SOURCE_NAME,
      sourceKind: INGESTION_SOURCE_KIND,
      fileUrl: context.registrationResponse.readUrl,
      url: context.knowledgeBaseUrl,
      baseUrl: this.sharepointBaseUrl,
    };

    try {
      await this.uniqueFileIngestionService.finalizeIngestion(ingestionFinalizationRequest);
      const _stepDuration = Date.now() - stepStartTime;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error({
        msg: 'Ingestion finalization failed',
        correlationId: context.correlationId,
        itemId: context.pipelineItem.item.id,
        driveId: context.pipelineItem.driveId,
        siteId: this.shouldConcealLogs
          ? smear(context.pipelineItem.siteId)
          : context.pipelineItem.siteId,
        error: message,
      });
      throw error;
    }
  }
}
