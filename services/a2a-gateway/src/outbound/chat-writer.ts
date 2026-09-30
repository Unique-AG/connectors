import { Logger } from '@nestjs/common';
import { z } from 'zod';
import type { RequestIdentity } from '../auth/identity.guard.js';
import type { UniqueInternalClient } from '../unique/unique-internal.client.js';

const PROGRESS_INTERVAL_MS = 250;
const PERSIST_INTERVAL_MS = 3_000;

const messageState = z.object({
  completedAt: z.string().nullish(),
  stoppedStreamingAt: z.string().nullish(),
  userAbortedAt: z.string().nullish(),
});

export interface ChatReference {
  name: string;
  url: string;
  sequenceNumber: number;
  sourceId: string;
  source: string;
}

/**
 * Writes one remote turn into its Unique assistant message under the effective user: throttled,
 * unpersisted progress events while streaming, periodic persistence, and exactly one final write.
 */
export class ChatWriter {
  private readonly logger = new Logger(ChatWriter.name);
  private lastText = '';
  private lastProgressAt = 0;
  private lastPersistAt = 0;

  public constructor(
    private readonly unique: UniqueInternalClient,
    private readonly identity: RequestIdentity,
    private readonly chatId: string,
    private readonly messageId: string,
  ) {}

  public async progress(text: string): Promise<void> {
    const now = Date.now();
    if (!text || text === this.lastText || now - this.lastProgressAt < PROGRESS_INTERVAL_MS) {
      return;
    }
    this.lastText = text;
    this.lastProgressAt = now;
    try {
      if (now - this.lastPersistAt >= PERSIST_INTERVAL_MS) {
        this.lastPersistAt = now;
        await this.unique.updateAssistantMessage(this.identity, this.chatId, this.messageId, {
          text,
        });
      } else {
        await this.unique.publishMessageProgress(this.identity, this.chatId, this.messageId, {
          text,
        });
      }
    } catch (error) {
      this.logger.warn({ msg: 'progress update failed', messageId: this.messageId, err: error });
    }
  }

  public async complete(text: string, references: ChatReference[] = []): Promise<void> {
    await this.unique.updateAssistantMessage(this.identity, this.chatId, this.messageId, {
      text,
      ...(references.length ? { references } : {}),
      completedAt: new Date().toISOString(),
    });
  }

  public async fail(text: string): Promise<void> {
    await this.unique.updateAssistantMessage(this.identity, this.chatId, this.messageId, {
      text,
      stoppedStreamingAt: new Date().toISOString(),
    });
  }

  /** Whether the user stopped the turn or it was otherwise finalised outside this run. */
  public async isClosed(): Promise<boolean> {
    const state = messageState.parse(
      await this.unique.getMessage(this.identity, this.chatId, this.messageId),
    );
    return Boolean(state.completedAt || state.stoppedStreamingAt || state.userAbortedAt);
  }
}
