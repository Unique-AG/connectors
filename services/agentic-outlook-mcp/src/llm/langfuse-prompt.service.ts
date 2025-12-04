import {
  ChatPromptClient,
  CreateChatPromptBodyWithPlaceholders,
  LangfuseClient,
  TextPromptClient,
} from '@langfuse/client';
import { Injectable, Logger } from '@nestjs/common';
import { isEqual } from 'lodash';

interface PromptOptions {
  name: string;
  type: 'text' | 'chat';
  prompt: string | Array<{ role: string; content: string }>;
  labels?: string[];
  config?: Record<string, unknown>;
}

@Injectable()
export class LangfusePromptService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly langfuse: LangfuseClient) {}

  public async ensurePrompt(options: PromptOptions): Promise<void> {
    const { name, type, prompt, labels, config } = options;

    let existingPrompt: TextPromptClient | ChatPromptClient | undefined;
    try {
      existingPrompt =
        type === 'text'
          ? await this.langfuse.prompt.get(name)
          : await this.langfuse.prompt.get(name, { type: 'chat' });
    } catch {
      /* not found, will create */
    }

    if (existingPrompt) {
      const isPromptSame = this.comparePrompts(type, existingPrompt.prompt, prompt);
      const isConfigSame = config ? isEqual(existingPrompt.config, config) : true;

      if (isPromptSame && isConfigSame) {
        this.logger.debug({
          msg: 'Prompt already exists and is up to date',
          prompt: name,
          type,
        });
        return;
      }
    }

    await this.langfuse.prompt.create({
      name,
      type,
      prompt,
      labels,
      config,
    } as CreateChatPromptBodyWithPlaceholders); // Unsafe cast, but langfuse sdk types are not ideal.

    this.logger.debug({
      msg: 'Prompt created or updated',
      prompt: name,
      type,
    });
  }

  private comparePrompts(
    type: 'text' | 'chat',
    existing: string | ChatPromptClient['prompt'],
    incoming: string | Array<{ role: string; content: string }>,
  ): boolean {
    if (type === 'text') return existing === incoming;

    if (!Array.isArray(existing) || !Array.isArray(incoming)) return false;

    if (existing.length !== incoming.length) return false;

    return existing.every((existingMsg, index) => {
      const incomingMsg = incoming[index];
      if (!('role' in existingMsg) || !('content' in existingMsg)) return false;
      const isSame =
        existingMsg.role === incomingMsg?.role && existingMsg.content === incomingMsg?.content;
      if (!isSame)
        this.logger.warn({
          msg: 'Prompt message mismatch',
          existingMsg,
          incomingMsg,
        });
      return isSame;
    });
  }
}
