import fs from 'node:fs';
import path from 'node:path';
import { Injectable, Logger } from '@nestjs/common';
import { compile } from 'handlebars';
import { serializeError } from 'serialize-error-cjs';
import { getFirstTextFromResponse } from '../../../../llm';
import { LLMService } from '../../../../llm/llm.service';
import { normalizeError } from '../../../../utils/normalize-error';

const MODEL = 'claude-haiku-4-5-20251001';

export interface SummarizationOutput {
  summarizedBody: string;
}

export class SummarizationError extends Error {
  public constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = 'SummarizationError';
  }
}

@Injectable()
export class LLMSummarizationService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly llmService: LLMService) {}

  public async summarize(text: string): Promise<SummarizationOutput> {
    try {
      const systemPrompt = this.buildSystemPrompt();
      const userPrompt = this.buildUserPrompt(text);

      const response = await this.llmService.client.responses.create({
        model: MODEL,
        instructions: systemPrompt,
        input: userPrompt,
      });

      const output = getFirstTextFromResponse(response);
      if (!output) throw new SummarizationError('No output text found in response');

      return {
        summarizedBody: output,
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to summarize body',
        error: serializeError(normalizeError(error)),
      });
      throw new SummarizationError('Failed to summarize body', error);
    }
  }

  private buildSystemPrompt(): string {
    try {
      const template = fs.readFileSync(
        path.join(__dirname, `${MODEL}.system-prompt.handlebars`),
        'utf8',
      );
      return compile(template)({});
    } catch (error) {
      throw new SummarizationError('Failed to load system prompt template', error);
    }
  }

  private buildUserPrompt(text: string): string {
    try {
      const template = fs.readFileSync(
        path.join(__dirname, `${MODEL}.user-prompt.handlebars`),
        'utf8',
      );
      return compile(template)({
        EMAIL_TEXT: text,
      });
    } catch (error) {
      throw new SummarizationError('Failed to load user prompt template', error);
    }
  }
}
