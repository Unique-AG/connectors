import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { UniqueAuthService } from '../auth/unique-auth.service';
import { DEFAULT_MIME_TYPE } from '../constants/defaults.constants';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { IPipelineStep } from './steps/pipeline-step.interface';
import type { ProcessingContext } from './types/processing-context';
import { PipelineStep } from './types/processing-context';

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
      const fileKey = this.generateFileKey(context);
      const registrationRequest = {
        key: fileKey,
        mimeType: context.metadata.mimeType ?? DEFAULT_MIME_TYPE,
        ownerType: 'SCOPE',
        scopeId: this.configService.get<string>('uniqueApi.scopeId') ?? 'unknown-scope',
        sourceOwnerType: 'USER',
        sourceKind: 'MICROSOFT_365_SHAREPOINT',
        sourceName: this.extractSiteName(context.siteUrl),
      } as const;

      this.logger.debug(`[${context.correlationId}] Registering content with key: ${fileKey}`);
      const registrationResponse = await this.uniqueApiService.registerContent(
        registrationRequest,
        uniqueToken,
      );
      context.uploadUrl = registrationResponse.writeUrl;
      context.uniqueContentId = registrationResponse.id ?? '';
      context.metadata.registration = registrationResponse;
      const _stepDuration = Date.now() - stepStartTime;
      return context;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.logger.error(`[${context.correlationId}] Content registration failed: ${message}`);
      throw error;
    }
  }

  private generateFileKey(context: ProcessingContext): string {
    const meta = context.metadata as Record<string, unknown>;
    const siteId = (meta.siteId as string | undefined) ?? 'unknown-site';
    const driveId = (meta.driveId as string | undefined) ?? 'unknown-drive';
    return `sharepoint_${siteId}_${driveId}_${context.fileId}`;
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
