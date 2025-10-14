import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { normalizeError } from '../../utils/normalize-error';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class AspxProcessingStep implements IPipelineStep {
  private readonly logger = new Logger(AspxProcessingStep.name);
  readonly stepName = PipelineStep.AspxProcessing;

  constructor(
    private readonly configService: ConfigService<Config, true>,
  ) {}

  async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const { fileName } = context;
    if (!fileName?.toLowerCase().endsWith('.aspx')) {
      return context;
    }

    const stepStart = Date.now();

    try {
      const htmlContent = this.buildHtmlFromAspx(context);
      context.contentBuffer = Buffer.from(htmlContent, 'utf-8');
      context.metadata.mimeType = 'text/html';
      return context;

    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(
        `[${context.correlationId}] ASPX processing failed: ${message}`,
      );
      throw error;
    }
  }

  /**
   * Builds an HTML representation of the ASPX page fields.
   */
  private buildHtmlFromAspx(context: ProcessingContext): string {
    const { metadata, fileName } = context;
    const fields = metadata?.listItemFields ?? {};
  
    const content = fields.CanvasContent1 || fields.WikiField || '';
    const title = fields.Title || fileName;
  
    return `
      <div>
        <h2>${title}</h2>
        ${content}
      </div>
    `.trim();
  }
}