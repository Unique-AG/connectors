import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { buildSharepointFileKey } from '../../shared/sharepoint-key.util';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import { normalizeError } from '../../utils/normalize-error';
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
    const registrationResponse = context.metadata.registration;
    const baseUrl = this.configService.get('uniqueApi.sharepointBaseUrl', { infer: true });
    const scopeId = this.configService.get('uniqueApi.scopeId', { infer: true });
    const isPathBasedIngestion = !scopeId;
    const stepStartTime = Date.now();

    assert.ok(
      registrationResponse,
      `[${context.correlationId}] Ingestion finalization failed. Registration response not found in context - content registration may have failed`,
    );

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
      sourceOwnerType: UniqueOwnerType.Company,
      sourceName: this.extractSiteName(context.siteUrl),
      sourceKind: 'MICROSOFT_365_SHAREPOINT',
      fileUrl: registrationResponse.readUrl,
      ...(isPathBasedIngestion && {
        url: context.downloadUrl,
        baseUrl: baseUrl,
      }),
    };

    try {
      const uniqueToken = await this.uniqueAuthService.getToken();
      this.logger.debug(
        `[${context.correlationId}] Ingestion finalization request payload: ${JSON.stringify(ingestionFinalizationRequest, null, 2)}`,
      );
      await this.uniqueApiService.finalizeIngestion(ingestionFinalizationRequest, uniqueToken);
      const _stepDuration = Date.now() - stepStartTime;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
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
