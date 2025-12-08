import fs from 'node:fs';
import path from 'node:path';
import { LangfuseClient } from '@langfuse/client';
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { normalizeError } from '../../../utils/normalize-error';
import { LangfusePromptService } from '../../langfuse-prompt.service';
import { LLMService } from '../../llm.service';

const MODEL = 'openai-gpt-oss-120b';
const PROMPT_TEMPLATE_NAME = 'text-translation';

export const translationOutputSchema = z.object({
  translated_text: z.string(),
  was_translated: z.boolean(),
  detected_language: z.string().nullable(),
});

const promptConfig = z.object({
  model: z.literal(MODEL),
  temperature: z.number().min(0).max(1).default(0.3),
  top_p: z.number().min(0).max(1).default(1.0),
  max_tokens: z.number().int().positive().default(10_000),
});

export type TranslationOutput = {
  translatedText: string;
  wasTranslated: boolean;
  detectedLanguage: string | null;
};

export class TranslationError extends Error {
  public constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = 'TranslationError';
  }
}

@Injectable()
export class LLMTranslationService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly llmService: LLMService,
    private readonly langfuse: LangfuseClient,
    private readonly promptService: LangfusePromptService,
  ) {}

  public async onModuleInit(): Promise<void> {
    await this.ensurePromptTemplates();
  }

  public async translate(text: string): Promise<TranslationOutput> {
    try {
      const prompt = await this.langfuse.prompt.get(PROMPT_TEMPLATE_NAME, { type: 'chat' });
      const [systemMessage, userMessage] = prompt.compile({
        TEXT: text,
      });
      const config = promptConfig.parse(prompt.config);

      const response = await this.llmService.generateObject(
        {
          ...config,
          messages: [systemMessage, userMessage],
          schema: translationOutputSchema,
        },
        {
          generationName: 'translate-text',
          langfusePrompt: prompt,
        },
      );

      return {
        translatedText: response.translated_text,
        wasTranslated: response.was_translated,
        detectedLanguage: response.detected_language,
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to translate text',
        error: serializeError(normalizeError(error)),
      });
      throw new TranslationError('Failed to translate text', error);
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
        temperature: 0.3,
        top_p: 1.0,
        max_tokens: 10_000,
      },
    });
  }
}
