import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class IngestionFinalizationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.INGESTION_FINALIZATION;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly uniqueApiService: UniqueApiService,
    private readonly configService: ConfigService,
  ) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();
    try {
      this.logger.debug(
        `[${context.correlationId}] Starting ingestion finalization for file: ${context.fileName}`,
      );
      const uniqueToken = await this.uniqueAuthService.getToken();
      const registrationResponse = context.metadata.registration;
      if (!registrationResponse) {
        throw new Error(
          'Registration response not found in context - content registration may have failed',
        );
      }
      const scopeId = this.configService.get<string | undefined>('uniqueApi.scopeId');
      const isPathMode = !scopeId;
      const baseUrl = this.configService.get<string | undefined>('uniqueApi.sharepointBaseUrl');

      const ingestionFinalizationRequest = {
        key: registrationResponse.key,
        title: context.fileName,
        mimeType: registrationResponse.mimeType,
        ownerType: registrationResponse.ownerType,
        byteSize: registrationResponse.byteSize,
        scopeId: scopeId ?? 'PATH',
        sourceOwnerType: 'USER',
        sourceName: this.extractSiteName(context.siteUrl),
        sourceKind: 'MICROSOFT_365_SHAREPOINT',
        fileUrl: registrationResponse.readUrl,
        url: isPathMode ? context.downloadUrl : undefined,
        baseUrl: isPathMode ? baseUrl : undefined,
      };

      this.logger.debug(
        `[${context.correlationId}] Finalizing ingestion for content ID: ${context.uniqueContentId}`,
      );

      const finalizationResponse = await this.uniqueApiService.finalizeIngestion(
        ingestionFinalizationRequest,
        uniqueToken,
      );

      if (!finalizationResponse.id) {
        throw new Error('Finalization response missing required field: id');
      }

      context.metadata.finalization = finalizationResponse;
      context.metadata.finalContentId = finalizationResponse.id;
      const _stepDuration = Date.now() - stepStartTime;
      return context;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.logger.error(`[${context.correlationId}] Ingestion finalization failed: ${message}`);
      throw error;
    }
  }

  private extractSiteName(siteUrl: string): string {
    if (!siteUrl) return 'SharePoint';
    try {
      const url = new URL(siteUrl);
      const pathParts = url.pathname.split('/').filter(Boolean);
      if (pathParts.length >= 2 && pathParts[0] === 'sites') {
        return pathParts[1] || url.hostname;
      }
      return url.hostname;
    } catch {
      return 'SharePoint';
    }
  }
}
