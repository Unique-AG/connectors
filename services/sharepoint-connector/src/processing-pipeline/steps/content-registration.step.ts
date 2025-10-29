import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import {
  INGESTION_SOURCE_KIND,
  INGESTION_SOURCE_NAME,
  IngestionMode,
} from '../../constants/ingestion.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { getScopeIdForIngestion } from '../../unique-api/ingestion.util';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { ContentRegistrationRequest } from '../../unique-api/unique-api.types';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import { normalizeError } from '../../utils/normalize-error';
import { buildIngetionItemKey } from '../../utils/sharepoint.util';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class ContentRegistrationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.ContentRegistration;
  private readonly ingestionMode: IngestionMode;
  private readonly scopeId: string | undefined;
  private readonly rootScopeName: string | undefined;
  private readonly sharepointBaseUrl: string;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly uniqueApiService: UniqueApiService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.ingestionMode = this.configService.get('unique.ingestionMode', { infer: true });
    this.scopeId = this.configService.get('unique.scopeId', { infer: true });
    this.rootScopeName = this.configService.get('unique.rootScopeName', { infer: true });
    this.sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
  }

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();

    const scopeId = getScopeIdForIngestion(this.ingestionMode, this.scopeId);

    const itemKey = buildIngetionItemKey(context.pipelineItem);
    const baseUrl = this.rootScopeName || this.sharepointBaseUrl;

    const contentRegistrationRequest: ContentRegistrationRequest = {
      key: itemKey,
      title: context.pipelineItem.fileName,
      mimeType: context.mimeType ?? DEFAULT_MIME_TYPE,
      ownerType: UniqueOwnerType.Scope,
      scopeId: scopeId,
      sourceOwnerType: UniqueOwnerType.Company,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      ...(this.ingestionMode === IngestionMode.Recursive && {
        url: context.knowledgeBaseUrl,
        baseUrl,
      }),
    };
    this.logger.debug(
      `contentRegistrationRequest: ${JSON.stringify(
        {
          url: contentRegistrationRequest.url,
          baseUrl: contentRegistrationRequest.baseUrl,
          key: contentRegistrationRequest.key,
          sourceName: contentRegistrationRequest.sourceName,
        },
        null,
        4,
      )}`,
    );

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
