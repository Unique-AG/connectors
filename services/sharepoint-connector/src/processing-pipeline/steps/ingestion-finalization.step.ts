import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import {
  INGESTION_SOURCE_KIND,
  INGESTION_SOURCE_NAME,
  PATH_BASED_INGESTION,
} from '../../constants/ingestion.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import { normalizeError } from '../../utils/normalize-error';
import { buildKnowledgeBaseFileKey } from '../../utils/sharepoint.util';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class IngestionFinalizationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.IngestionFinalization;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly uniqueApiService: UniqueApiService,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const rootScopeName = this.configService.get('unique.rootScopeName', { infer: true });
    const scopeId = this.configService.get('unique.scopeId', { infer: true });
    const sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    const isPathBasedIngestion = !scopeId;
    const stepStartTime = Date.now();

    assert.ok(
      context.registrationResponse,
      `[${context.correlationId}] Ingestion finalization failed. Registration response not found in context - content registration may have failed`,
    );

    const fileKey = buildKnowledgeBaseFileKey(context.pipelineItem);

    const baseUrl = rootScopeName || sharepointBaseUrl;

    const ingestionFinalizationRequest = {
      key: fileKey,
      title: context.pipelineItem.fileName,
      mimeType: context.registrationResponse.mimeType,
      ownerType: context.registrationResponse.ownerType,
      byteSize: context.registrationResponse.byteSize,
      scopeId: isPathBasedIngestion ? PATH_BASED_INGESTION : scopeId,
      sourceOwnerType: UniqueOwnerType.Company,
      sourceName: INGESTION_SOURCE_NAME,
      sourceKind: INGESTION_SOURCE_KIND,
      fileUrl: context.registrationResponse.readUrl,
      ...(isPathBasedIngestion && {
        url: context.knowledgeBaseUrl,
        baseUrl,
      }),
    };

    try {
      const uniqueToken = await this.uniqueAuthService.getToken();

      await this.uniqueApiService.finalizeIngestion(ingestionFinalizationRequest, uniqueToken);
      const _stepDuration = Date.now() - stepStartTime;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] Ingestion finalization failed: ${message}`);
      throw error;
    }
  }
}
