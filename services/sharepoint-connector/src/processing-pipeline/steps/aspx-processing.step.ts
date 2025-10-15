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
  public readonly stepName = PipelineStep.AspxProcessing;

  public constructor(private readonly configService: ConfigService<Config, true>) {}

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const { fileName } = context;
    if (!this.isAspxFile(fileName)) {
      return context;
    }

    try {
      const htmlContent = this.buildHtmlFromAspx(context);
      context.contentBuffer = Buffer.from(htmlContent, 'utf-8');
      context.metadata.mimeType = 'text/html';
      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error(`[${context.correlationId}] ASPX processing failed: ${message}`);
      throw error;
    }
  }

  private isAspxFile(fileName: string | undefined): boolean {
    return fileName?.toLowerCase().endsWith('.aspx') ?? false;
  }

  private buildHtmlFromAspx(context: ProcessingContext): string {
    const fields = context.metadata.listItemFields ?? {};
    const sharepointBaseUrl = this.getSharepointBaseUrl();

    const content = this.extractContent(fields);
    const processedContent = this.processRelativeLinks(content, sharepointBaseUrl);
    const title = this.extractTitle(fields, context.fileName);
    const authorHtml = this.buildAuthorHtml(fields);

    return this.buildHtmlStructure(title, authorHtml, processedContent);
  }

  // Prioritize CanvasContent1 (modern) over WikiField (legacy) for SharePoint compatibility
  private extractContent(fields: Record<string, unknown>): string {
    return (fields.CanvasContent1 as string) || (fields.WikiField as string) || '';
  }

  private processRelativeLinks(content: string, baseUrl: string): string {
    if (!content || !baseUrl) {
      return content;
    }

    return content.replace(/href="\/([^"]*)"/g, `href="${baseUrl}/$1"`);
  }

  private extractTitle(fields: Record<string, unknown>, fallbackFileName: string): string {
    return (fields.Title as string) || fallbackFileName;
  }

  private buildAuthorHtml(fields: Record<string, unknown>): string {
    const author = fields.Author as Record<string, unknown>;
    if (!author) {
      return '';
    }

    const firstName = author.FirstName as string;
    const lastName = author.LastName as string;

    if (!firstName && !lastName) {
      return '';
    }

    const fullName = [firstName, lastName].filter(Boolean).join(' ');
    return `<h4>${fullName}</h4>`;
  }

  private buildHtmlStructure(title: string, authorHtml: string, content: string): string {
    return `<div><h2>${title}</h2>${authorHtml}${content}</div>`;
  }

  private getSharepointBaseUrl(): string {
    return this.configService.get('sharepoint.baseUrl', { infer: true });
  }
}
