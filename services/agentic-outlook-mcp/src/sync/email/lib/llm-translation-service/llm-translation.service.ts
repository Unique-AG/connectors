import fs from 'node:fs';
import path from 'node:path';
import { LangfuseClient } from '@langfuse/client';
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { LangfusePromptService } from '../../../../llm/langfuse-prompt.service';
import { LLMService } from '../../../../llm/llm.service';
import { normalizeError } from '../../../../utils/normalize-error';

const MODEL = 'openai-gpt-oss-120b';
const PROMPT_TEMPLATE_NAME = 'email-translation';

export const translationOutputSchema = z.object({
  translated_body: z.string(),
  translated_subject: z.string().nullable(),
});

const promptConfig = z.object({
  model: z.literal(MODEL),
  temperature: z.number().min(0).max(1).default(1.0),
  top_p: z.number().min(0).max(1).default(1.0),
  max_tokens: z.number().int().positive().default(30_000),
});

export type TranslationOutput = {
  body: string;
  subject: string | null;
}

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

  public async translate({ subject, body }: { subject: string | null; body: string }): Promise<TranslationOutput> {
    try {
      const prompt = await this.langfuse.prompt.get(PROMPT_TEMPLATE_NAME, { type: 'chat' });
      const [systemMessage, userMessage] = prompt.compile({
        SUBJECT: subject ?? '',
        BODY: body,
      });
      const config = promptConfig.parse(prompt.config);

      const response = await this.llmService.generateObject({
        ...config,
        messages: [systemMessage, userMessage],
        schema: translationOutputSchema,
      }, {
        generationName: 'translate',
        langfusePrompt: prompt,
      });

      return {
        body: response.translated_body,
        subject: response.translated_subject,
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
        temperature: 1.0,
        top_p: 1.0,
        max_tokens: 30_000,
      },
    });
  }
}
