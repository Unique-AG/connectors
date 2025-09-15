import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { UniqueAuthService } from '../auth/unique-auth.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { IPipelineStep } from './steps/pipeline-step.interface';
import type { ProcessingContext } from './types/processing-context';
import { PipelineStep } from './types/processing-context';

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
      const registrationResponse = context.metadata.registrationResponse;
      if (!registrationResponse) {
        throw new Error(
          'Registration response not found in context - content registration may have failed',
        );
      }
      const finalizationRequest = {
        key: registrationResponse.key,
        mimeType: registrationResponse.mimeType,
        ownerType: registrationResponse.ownerType,
        byteSize: registrationResponse.byteSize,
        scopeId: this.configService.get<string>('uniqueApi.scopeId') ?? 'unknown-scope',
        sourceOwnerType: 'USER',
        sourceName: this.extractSiteName(context.siteUrl),
        sourceKind: 'MICROSOFT_365_SHAREPOINT',
        fileUrl: registrationResponse.readUrl,
      } as const;

      this.logger.debug(
        `[${context.correlationId}] Finalizing ingestion for content ID: ${String(
          context.uniqueContentId ?? '',
        )}`,
      );
      const finalizationResponse = await this.uniqueApiService.finalizeIngestion(
        finalizationRequest,
        uniqueToken,
      );
      context.metadata.finalizationResponse = finalizationResponse;
      context.metadata.finalContentId = finalizationResponse.id ?? '';
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
