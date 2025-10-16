import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { isListItem} from '../../msgraph/types/type-guards.util';
import { normalizeError } from '../../utils/normalize-error';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';
import {ListItem} from "../../msgraph/types/sharepoint.types";
import {getTitle} from "../../utils/list-item.util";

@Injectable()
export class AspxProcessingStep implements IPipelineStep {
  private readonly logger = new Logger(AspxProcessingStep.name);
  public readonly stepName = PipelineStep.AspxProcessing;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
  ) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    if (!isListItem(context.pipelineItem)) {
      return context;
    }

    try {
      const htmlContent = this.buildHtmlContent(context, context.pipelineItem.item);
      context.contentBuffer = Buffer.from(htmlContent, 'utf-8');
      context.mimeType = 'text/html';

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] ASPX processing failed: ${message}`);
      throw error;
    }
  }

  private buildHtmlContent(context: ProcessingContext, item: ListItem): string {
    const rawContent = context.contentBuffer?.toString('utf-8') || '';
    const sharepointBaseUrl = this.getSharepointBaseUrl();

    const processedContent = this.convertRelativeLinks(rawContent, sharepointBaseUrl);
    const authorHtml = this.buildAuthorHtml(item.createdBy);
    const title = getTitle(item.fields);

    return this.buildHtmlStructure(title, authorHtml, processedContent);
  }

  private convertRelativeLinks(content: string, baseUrl: string): string {
    if (!content || !baseUrl) {
      return content;
    }

    // adds base url to strings that start with href=/
    return content.replace(/href="\/(.*?)"/g, `href="${baseUrl}$1"`);
  }

  private buildAuthorHtml(createdBy: ListItem['createdBy'] ): string {
    return `<h4>${createdBy.user.displayName}</h4>`;
  }

  private buildHtmlStructure(title: string, authorHtml: string, content: string): string {
    return `<div><h2>${title}</h2>${authorHtml}${content}</div>`;
  }

  private getSharepointBaseUrl(): string {
    return this.configService.get('sharepoint.baseUrl', { infer: true });
  }
}
