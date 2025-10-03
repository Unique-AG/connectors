import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { buildSharepointFileKey } from '../../shared/sharepoint-key.util';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { ContentRegistrationRequest } from '../../unique-api/unique-api.types';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';
import {normalizeError} from "../../utils/normalize-error";

@Injectable()
export class ContentRegistrationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.CONTENT_REGISTRATION;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly uniqueApiService: UniqueApiService,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();

    this.logger.debug(
      `[${context.correlationId}] Starting content registration for file: ${context.fileName}`,
    );

    try {
      const uniqueToken = await this.uniqueAuthService.getToken();
      const scopeId = this.configService.get('uniqueApi.scopeId', { infer: true });
      const baseUrl = this.configService.get('uniqueApi.sharepointBaseUrl', { infer: true });
      const isPathBasedIngestion = !scopeId;

      const fileKey = this.buildFileKey(context, scopeId);

      const contentRegistrationRequest: ContentRegistrationRequest = {
        key: fileKey,
        title: context.fileName,
        mimeType: context.metadata.mimeType ?? DEFAULT_MIME_TYPE,
        ownerType: UniqueOwnerType.Scope,
        scopeId: isPathBasedIngestion ? 'PATH' : scopeId,
        sourceOwnerType: UniqueOwnerType.Company,
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
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] Content registration failed: ${message}`);
      throw error;
    }
  }

  private buildFileKey(context: ProcessingContext, scopeId: string | undefined): string {
    return buildSharepointFileKey({
      scopeId,
      siteId: context.metadata.siteId,
      driveName: context.metadata.driveName,
      folderPath: context.metadata.folderPath,
      fileId: context.fileId,
      fileName: context.fileName,
    });
  }
}
