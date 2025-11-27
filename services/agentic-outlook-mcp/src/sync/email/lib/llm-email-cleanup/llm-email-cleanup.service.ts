import fs from 'node:fs';
import path from 'node:path';
import { LangfuseClient } from '@langfuse/client';
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { Email } from '../../../../drizzle';
import { LangfusePromptService } from '../../../../llm/langfuse-prompt.service';
import { LLMService } from '../../../../llm/llm.service';
import { normalizeError } from '../../../../utils/normalize-error';

const MODEL = 'openai-gpt-oss-120b';

const PROMPT_TEMPLATE_NAME = 'email-cleanup';

export const emailCleanupOutputSchema = z.object({
  clean_markdown: z.string(),
  clean_text: z.string(),
  removed_blocks: z.array(
    z.object({
      type: z.enum(['banner', 'signature', 'legal', 'thread', 'tracking', 'other']),
      reason: z.string(),
      confidence: z.number().min(0).max(1),
    }),
  ),
  meta: z.object({
    language: z.string(),
    had_banner: z.boolean(),
    had_signature: z.boolean(),
    had_legal: z.boolean(),
    had_thread: z.boolean(),
    kept_links_count: z.number(),
    removed_links_count: z.number(),
  }),
});

export const promptConfig = z.object({
  model: z.string(),
  temperature: z.number(),
  top_p: z.number(),
  max_tokens: z.number(),
});

export type EmailCleanupOutput = z.infer<typeof emailCleanupOutputSchema>;

export interface CleanedEmail {
  cleanMarkdown: string;
  cleanText: string;
  removedBlocks: EmailCleanupOutput['removed_blocks'];
  meta: EmailCleanupOutput['meta'];
}

export class EmailCleanupError extends Error {
  public constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = 'EmailCleanupError';
  }
}

export class EmailCleanupParseError extends EmailCleanupError {
  public constructor(
    message: string,
    public readonly rawOutput?: string,
    cause?: unknown,
  ) {
    super(message, cause);
    this.name = 'EmailCleanupParseError';
  }
}

export class EmailCleanupAPIError extends EmailCleanupError {
  public constructor(message: string, cause?: unknown) {
    super(message, cause);
    this.name = 'EmailCleanupAPIError';
  }
}

@Injectable()
export class LLMEmailCleanupService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly llmService: LLMService,
    private readonly langfuse: LangfuseClient,
    private readonly promptService: LangfusePromptService,
  ) {}

  public async onModuleInit(): Promise<void> {
    await this.ensurePromptTemplates();
  }

  public async cleanupEmail(email: Email): Promise<CleanedEmail> {
    try {
      const prompt = await this.langfuse.prompt.get(PROMPT_TEMPLATE_NAME, { type: 'chat' });
      const compiledPrompt = prompt.compile({
        EMAIL_SUBJECT: email.subject ?? '',
        EMAIL_FROM: email.from?.address ?? '',
        EMAIL_TO: email.to.map((to) => to.address).join(', '),
        EMAIL_DATE: email.receivedAt ?? '',
        EMAIL_PLAIN_TEXT: email.bodyText ?? '',
        EMAIL_HTML: email.uniqueBodyHtml ?? '',
      });
      const config = promptConfig.parse(prompt.config);

      const response = await this.llmService.generateObject(
        {
          ...config,
          messages: compiledPrompt,
          schema: emailCleanupOutputSchema,
        },
        {
          generationName: 'email-cleanup',
          langfusePrompt: prompt,
        },
      );

      this.logger.debug({
        msg: 'Email cleanup successful',
        emailId: email.id,
        removedBlocksCount: response.removed_blocks.length,
        meta: response.meta,
      });

      return {
        cleanMarkdown: response.clean_markdown,
        cleanText: response.clean_text,
        removedBlocks: response.removed_blocks,
        meta: response.meta,
      };
    } catch (error) {
      if (error instanceof EmailCleanupError) throw error;

      this.logger.error({
        msg: 'Unexpected error during email cleanup',
        emailId: email.id,
        error: serializeError(normalizeError(error)),
      });

      throw new EmailCleanupError(`Failed to cleanup email ${email.id}`, error);
    }
  }

  private async ensurePromptTemplates(): Promise<void> {
    const systemPromptTemplate = fs.readFileSync(path.join(__dirname, `system-prompt.txt`), 'utf8');
    const userPromptTemplate = fs.readFileSync(path.join(__dirname, `user-prompt.txt`), 'utf8');

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
