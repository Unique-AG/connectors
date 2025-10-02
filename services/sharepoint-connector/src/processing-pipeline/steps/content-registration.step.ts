import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { ContentRegistrationRequest } from '../../unique-api/unique-api.types';
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
    try {
      this.logger.debug(
        `[${context.correlationId}] Starting content registration for file: ${context.fileName}`,
      );
      const uniqueToken = await this.uniqueAuthService.getToken();
      const scopeId = this.configService.get<string | undefined>('uniqueApi.scopeId');
      const fileKey = this.generateFileKey(context, scopeId);
      
      this.logger.log(
        `[${context.correlationId}] Generated file key for ingestion: ${fileKey}`,
      );
      
      const isPathMode = !scopeId;
      const baseUrl = this.configService.get<string | undefined>('uniqueApi.sharepointBaseUrl');

      const contentRegistrationRequest: ContentRegistrationRequest = {
        key: fileKey,
        title: context.fileName,
        mimeType: context.metadata.mimeType ?? DEFAULT_MIME_TYPE,
        ownerType: 'SCOPE',
        scopeId: scopeId ?? 'PATH',
        sourceOwnerType: 'USER',
        sourceKind: 'MICROSOFT_365_SHAREPOINT',
        sourceName: 'Sharepoint',
        url: isPathMode ? context.downloadUrl : undefined,
        baseUrl: isPathMode ? baseUrl : undefined,
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

  private generateFileKey(context: ProcessingContext, scopeId: string | undefined): string {
    const siteId = context.metadata.siteId;
    const driveName = context.metadata.driveName;
    const folderPath = context.metadata.folderPath;

    if (!scopeId) {
      const cleanFolderPath = folderPath.replace(/^\/+|\/+$/g, '');
      const pathParts = [siteId, driveName];
      
      if (cleanFolderPath) {
        pathParts.push(cleanFolderPath);
      }
      
      pathParts.push(context.fileName);
      
      return pathParts.join('/');
    }

    return `sharepoint_${siteId}_${context.fileId}`;
  }
}
