import fs from 'node:fs';
import path from 'node:path';
import { Injectable, Logger } from '@nestjs/common';
import { compile } from 'handlebars';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { Email } from '../../../../drizzle';
import { LLMService } from '../../../../llm/llm.service';
import { normalizeError } from '../../../../utils/normalize-error';
import { FEW_SHOT_EXAMPLES } from './few-shot.examples';

const DEFAULT_KNOWN_DOMAINS = [
  'aka.ms',
  'microsoft.com',
  'proofpoint.com',
  'barracuda.com',
  'postini.com',
  'menlosecurity.com',
  'mimecast.com',
  'cofense.com',
  'ironscales.com',
  'trendmicro.com',
];

const ORG_BANNER_PHRASES = [
  'EXTERNAL EMAIL',
  'This message came from outside your organization',
  "You don't often get email from ...",
  'Learn why this is important',
];

const LANGUAGES = ['en', 'de', 'fr'];

const MODEL = 'claude-haiku-4-5-20251001';

export const emailCleanupOutputSchema = z.object({
  clean_markdown: z.string(),
  clean_text: z.string(),
  removed_blocks: z.array(
    z.object({
      type: z.enum(['banner', 'signature', 'legal', 'thread', 'tracking', 'other']),
      reason: z.string(),
      confidence: z.number().min(0).max(1),
      excerpt: z.string().max(300),
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
    notes: z.string().optional(),
  }),
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
export class LLMEmailCleanupService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly llmService: LLMService) {}

  public async cleanupEmail(email: Email): Promise<CleanedEmail> {
    try {
      const systemPrompt = this.buildSystemPrompt();
      const userPrompt = this.buildUserPrompt(email);

      const response = await this.llmService.generateObject({
        model: MODEL,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: userPrompt },
        ],
        schema: emailCleanupOutputSchema,
      });

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

  private buildSystemPrompt(): string {
    try {
      const template = fs.readFileSync(
        path.join(__dirname, `${MODEL}.system-prompt.handlebars`),
        'utf8',
      );
      return compile(template)({
        KNOWN_DOMAINS: DEFAULT_KNOWN_DOMAINS.join(', '),
        ORG_BANNER_PHRASES: ORG_BANNER_PHRASES.join(', '),
      });
    } catch (error) {
      throw new EmailCleanupError('Failed to load system prompt template', error);
    }
  }

  private buildUserPrompt(email: Email): string {
    try {
      const template = fs.readFileSync(
        path.join(__dirname, `${MODEL}.user-prompt.handlebars`),
        'utf8',
      );
      return compile(template)({
        ORG_BANNER_PHRASES: ORG_BANNER_PHRASES.join(', '),
        KNOWN_DOMAINS: DEFAULT_KNOWN_DOMAINS.join(', '),
        LANGUAGES: LANGUAGES.join(', '),
        FEW_SHOT_BLOCKS: FEW_SHOT_EXAMPLES,
        EMAIL: {
          SUBJECT: email.subject,
          FROM: `${email.from?.name} <${email.from?.address}>`,
          TO: email.to.map((to) => `${to.name} <${to.address}>`).join(', '),
          DATE: email.receivedAt,
          PLAIN_TEXT: email.bodyText,
          HTML: email.uniqueBodyHtml,
        },
      });
    } catch (error) {
      throw new EmailCleanupError('Failed to load user prompt template', error);
    }
  }
}
