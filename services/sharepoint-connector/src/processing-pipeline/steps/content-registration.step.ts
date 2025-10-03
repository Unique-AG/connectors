import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { ContentRegistrationRequest } from '../../unique-api/unique-api.types';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class ContentRegistrationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.CONTENT_REGISTRATION;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly uniqueApiService: UniqueApiService,
    private readonly configService: ConfigService,
  ) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();

    this.logger.debug(
      `[${context.correlationId}] Starting content registration for file: ${context.fileName}`,
    );

    try {
      const uniqueToken = await this.uniqueAuthService.getToken();
      const scopeId = this.configService.get<string>('uniqueApi.scopeId');
      const baseUrl = <string>this.configService.get('uniqueApi.sharepointBaseUrl');
      const isPathBasedIngestion = !scopeId;

      const fileKey = this.generateFileKey(context, isPathBasedIngestion);

      const contentRegistrationRequest: ContentRegistrationRequest = {
        key: fileKey,
        title: context.fileName,
        mimeType: context.metadata.mimeType ?? DEFAULT_MIME_TYPE,
        ownerType: UniqueOwnerType.SCOPE,
        scopeId: isPathBasedIngestion ? 'PATH' : scopeId,
        sourceOwnerType: UniqueOwnerType.COMPANY,
        sourceKind: 'MICROSOFT_365_SHAREPOINT',
        sourceName: 'Sharepoint',
        ...(isPathBasedIngestion && {
          url: context.downloadUrl,
          baseUrl: baseUrl,
        }),
      };

      this.logger.debug(`[${context.correlationId}] Registering content with key: ${fileKey}`);
      const registrationResponse = await this.uniqueApiService.registerContent(
        contentRegistrationRequest,
        uniqueToken,
      );

      if (!registrationResponse.writeUrl) {
        throw new Error('Registration response missing required fields: id or writeUrl');
      }

      context.uploadUrl = registrationResponse.writeUrl;
      context.uniqueContentId = registrationResponse.id;
      context.metadata.registration = registrationResponse;
      const _stepDuration = Date.now() - stepStartTime;

      return context;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.logger.error(`[${context.correlationId}] Content registration failed: ${message}`);
      throw error;
    }
  }

  private generateFileKey(context: ProcessingContext, isPathBasedIngestion: boolean): string {
    if (!isPathBasedIngestion) {
      return `sharepoint_${context.metadata.siteId}_${context.fileId}`;
    }

    const cleanFolderPath = context.metadata.folderPath.replace(/^\/+|\/+$/g, '');
    return [
      context.metadata.siteId,
      context.metadata.driveName,
      cleanFolderPath,
      context.fileName,
    ].join('/');
  }
}
