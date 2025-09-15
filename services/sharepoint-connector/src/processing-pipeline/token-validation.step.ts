import { Injectable, Logger } from '@nestjs/common';
import { SharepointAuthService } from '../auth/sharepoint-auth.service';
import { UniqueAuthService } from '../auth/unique-auth.service';
import type { IPipelineStep } from './steps/pipeline-step.interface';
import type { ProcessingContext } from './types/processing-context';
import { PipelineStep } from './types/processing-context';

@Injectable()
export class TokenValidationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.TOKEN_VALIDATION;

  public constructor(
    private readonly sharepointAuthService: SharepointAuthService,
    private readonly uniqueAuthService: UniqueAuthService,
  ) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();
    try {
      this.logger.debug(
        `[${context.correlationId}] Starting token validation for file: ${context.fileName}`,
      );
      const [graphToken, uniqueToken] = await Promise.all([
        this.sharepointAuthService.getToken(),
        this.uniqueAuthService.getToken(),
      ]);
      if (!graphToken || !uniqueToken) {
        throw new Error(
          `Failed to obtain valid token from ${graphToken ? 'Zitadel' : 'Microsoft Graph'}`,
        );
      }
      context.metadata.tokens = {
        graphApiToken: graphToken,
        uniqueApiToken: uniqueToken,
        validatedAt: new Date().toISOString(),
      };
      const _stepDuration = Date.now() - stepStartTime;
      return context;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.logger.error(`${context.correlationId} Token validation failed: ${message}`);
      throw error;
    }
  }
}
