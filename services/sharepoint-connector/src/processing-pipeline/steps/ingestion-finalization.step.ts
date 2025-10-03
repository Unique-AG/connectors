import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { buildSharepointFileKey } from '../../shared/sharepoint-key.util';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
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
    const registrationResponse = context.metadata.registration;
    const baseUrl = <string>this.configService.get('uniqueApi.sharepointBaseUrl');
    const scopeId = this.configService.get<string | undefined>('uniqueApi.scopeId');
    const isPathBasedIngestion = !scopeId;

    if (!registrationResponse) {
      throw new Error(
        `[${context.correlationId}] Ingestion finalization failed. Registration response not found in context - content registration may have failed`,
      );
    }

    this.logger.debug(
      `[${context.correlationId}] Starting ingestion finalization for file: ${context.fileName}`,
    );

    try {
      const stepStartTime = Date.now();
      const uniqueToken = await this.uniqueAuthService.getToken();

      const ingestionFinalizationRequest = {
        key: buildSharepointFileKey({
          scopeId,
          siteId: context.metadata.siteId,
          driveName: context.metadata.driveName,
          folderPath: context.metadata.folderPath,
          fileId: context.fileId,
          fileName: context.fileName,
        }),
        title: context.fileName,
        mimeType: registrationResponse.mimeType,
        ownerType: registrationResponse.ownerType,
        byteSize: registrationResponse.byteSize,
        scopeId: isPathBasedIngestion ? 'PATH' : scopeId,
        sourceOwnerType: UniqueOwnerType.COMPANY,
        sourceName: this.extractSiteName(context.siteUrl),
        sourceKind: 'MICROSOFT_365_SHAREPOINT',
        fileUrl: registrationResponse.readUrl,
        ...(isPathBasedIngestion && {
          url: context.downloadUrl,
          baseUrl: baseUrl,
        }),
      };

      await this.uniqueApiService.finalizeIngestion(ingestionFinalizationRequest, uniqueToken);

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
