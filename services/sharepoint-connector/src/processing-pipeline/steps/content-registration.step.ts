import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import {
  INGESTION_SOURCE_KIND,
  INGESTION_SOURCE_NAME,
  PATH_BASED_INGESTION,
} from '../../constants/ingestion.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { ContentRegistrationRequest } from '../../unique-api/unique-api.types';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import { normalizeError } from '../../utils/normalize-error';
import { buildFileDiffKey } from '../../utils/sharepoint.util';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class ContentRegistrationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.ContentRegistration;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly uniqueApiService: UniqueApiService,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();
    const scopeId = this.configService.get('unique.scopeId', { infer: true });
    const rootScopeName = this.configService.get('unique.rootScopeName', { infer: true });

    const isPathBasedIngestion = !scopeId;

    const itemKey = buildFileDiffKey(context.pipelineItem);
    const contentRegistrationRequest: ContentRegistrationRequest = {
      key: itemKey,
      title: context.pipelineItem.fileName,
      mimeType: context.mimeType ?? DEFAULT_MIME_TYPE,
      ownerType: UniqueOwnerType.Scope,
      scopeId: isPathBasedIngestion ? PATH_BASED_INGESTION : scopeId,
      sourceOwnerType: UniqueOwnerType.Company,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      ...(isPathBasedIngestion && {
        url: context.knowledgeBaseUrl,
        baseUrl: rootScopeName,
      }),
    };

    try {
      const uniqueToken = await this.uniqueAuthService.getToken();
      const registrationResponse = await this.uniqueApiService.registerContent(
        contentRegistrationRequest,
        uniqueToken,
      );

      assert.ok(
        registrationResponse.writeUrl,
        'Registration response missing required fields: id or writeUrl',
      );

      context.uploadUrl = registrationResponse.writeUrl;
      context.uniqueContentId = registrationResponse.id;
      context.registrationResponse = registrationResponse;
      const _stepDuration = Date.now() - stepStartTime;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] Content registration failed: ${message}`);
      throw error;
    }
  }
}
