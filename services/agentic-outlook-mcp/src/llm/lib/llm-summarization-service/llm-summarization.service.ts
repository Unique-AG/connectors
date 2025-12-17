import fs from 'node:fs';
import path from 'node:path';
import { LangfuseClient } from '@langfuse/client';
import { observeOpenAI } from '@langfuse/openai';
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { serializeError } from 'serialize-error-cjs';
import { normalizeError } from '../../../utils/normalize-error';
import { LangfusePromptService } from '../../langfuse-prompt.service';
import { LLMService } from '../../llm.service';
import { getFirstTextFromResponse } from '../../parse-openai.util';

const MODEL = 'openai-gpt-oss-120b';
const PROMPT_TEMPLATE_NAME = 'email-summarization';

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
export class LLMSummarizationService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly llmService: LLMService,
    private readonly langfuse: LangfuseClient,
    private readonly promptService: LangfusePromptService,
  ) {}

  public async onModuleInit(): Promise<void> {
    await this.ensurePromptTemplates();
  }

  public async summarize(text: string): Promise<SummarizationOutput> {
    try {
      const prompt = await this.langfuse.prompt.get(PROMPT_TEMPLATE_NAME, { type: 'chat' });
      const [systemMessage, userMessage] = prompt.compile({
        EMAIL_TEXT: text,
      });

      const response = await observeOpenAI(this.llmService.rawClient, {
        generationName: 'summarize',
        langfusePrompt: prompt,
      }).responses.create({
        model: MODEL,
        instructions: systemMessage.content,
        input: userMessage.content,
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

  private async ensurePromptTemplates(): Promise<void> {
    const systemPromptTemplate = fs.readFileSync(path.join(__dirname, 'system-prompt.txt'), 'utf8');
    const userPromptTemplate = fs.readFileSync(path.join(__dirname, 'user-prompt.txt'), 'utf8');

    await this.promptService.ensurePrompt({
      name: PROMPT_TEMPLATE_NAME,
      type: 'chat',
      prompt: [
        { role: 'system', content: systemPromptTemplate },
        { role: 'user', content: userPromptTemplate },
      ],
      labels: ['production', MODEL],
      config: {
        model: MODEL,
        temperature: 1.0,
        top_p: 1.0,
        max_tokens: 10_000,
      },
    });
  }
}
