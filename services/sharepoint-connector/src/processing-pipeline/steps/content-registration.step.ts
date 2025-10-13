import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { buildSharepointFileKey } from '../../shared/sharepoint-key.util';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { ContentRegistrationRequest } from '../../unique-api/unique-api.types';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import { normalizeError } from '../../utils/normalize-error';
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
    const baseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    const isPathBasedIngestion = !scopeId;

    const fileKey = buildSharepointFileKey({
      scopeId,
      siteId: context.metadata.siteId,
      driveName: context.metadata.driveName,
      folderPath: context.metadata.folderPath,
      fileId: context.fileId,
      fileName: context.fileName,
    });

    const contentRegistrationRequest: ContentRegistrationRequest = {
      key: fileKey,
      title: context.fileName,
      mimeType: context.metadata.mimeType ?? DEFAULT_MIME_TYPE,
      ownerType: UniqueOwnerType.Scope,
      scopeId: isPathBasedIngestion ? 'PATH' : scopeId,
      sourceOwnerType: UniqueOwnerType.Company,
      sourceKind: 'MICROSOFT_365_SHAREPOINT',
      sourceName: 'SharePoint Online Connector',
      ...(isPathBasedIngestion && {
        url: context.knowledgeBaseUrl,
        baseUrl: baseUrl,
      }),
    };

    try {
      const uniqueToken = await this.uniqueAuthService.getToken();
      this.logger.debug(
        `[${context.correlationId}] Content registration request payload: ${JSON.stringify(contentRegistrationRequest, null, 2)}`,
      );
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
      context.metadata.registration = registrationResponse;
      const _stepDuration = Date.now() - stepStartTime;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] Content registration failed: ${message}`);
      throw error;
    }
  }
}
