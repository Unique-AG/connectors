import { Inject, Injectable } from '@nestjs/common';
import { z } from 'zod';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { ChatEventConsumer } from '../event-bus/chat-event.consumer.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';

const POLL_INTERVAL_MS = 3_000;
const HEARTBEAT_INTERVAL_MS = 30_000;

const TERMINAL_SEGMENT_KINDS = ['ANSWER', 'ELICITATION'];

const segmentSchema = z.object({
  id: z.string(),
  text: z.string().nullish(),
  segmentKind: z.string().nullish(),
  segmentIndex: z.number().nullish(),
  completedAt: z.string().nullish(),
  stoppedStreamingAt: z.string().nullish(),
  userAbortedAt: z.string().nullish(),
  references: z
    .array(
      z.object({
        name: z.string(),
        url: z.string().nullish(),
        sequenceNumber: z.number().nullish(),
        sourceId: z.string().nullish(),
        source: z.string().nullish(),
      }),
    )
    .nullish(),
});

const elicitationSchema = z.object({
  id: z.string(),
  userId: z.string(),
  status: z.string(),
  mode: z.enum(['FORM', 'URL']),
  message: z.string().nullish(),
  schema: z.unknown().optional(),
  url: z.string().nullish(),
});

export type NativeMessage = Omit<z.infer<typeof segmentSchema>, 'segmentKind' | 'segmentIndex'>;

export interface NativeTurn {
  chatId: string;
  userMessageId: string;
  /** The assistant shell (first segment) created for the turn. */
  messageId: string;
}
export type PendingElicitation = z.infer<typeof elicitationSchema>;

export type RunOutcome =
  | { kind: 'completed'; message: NativeMessage }
  | { kind: 'canceled'; message: NativeMessage }
  | { kind: 'failed'; message: NativeMessage }
  | { kind: 'elicitation'; elicitation: PendingElicitation };

export interface ObserveOptions {
  identity: RequestIdentity;
  turn: NativeTurn;
  onText?: (text: string) => Promise<void> | void;
  onHeartbeat?: () => Promise<void> | void;
}

const TERMINAL_EVENT_FIELDS = ['completedAt', 'stoppedStreamingAt', 'userAbortedAt'];

/**
 * Follows one native assistant turn until it settles. Bus events only trigger re-reads; core is
 * polled as well, so missed events or a restarted gateway never lose the outcome.
 */
@Injectable()
export class NativeRunObserver {
  public constructor(
    private readonly events: ChatEventConsumer,
    private readonly unique: UniqueInternalClient,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  /** Derives the turn's state from core; multi-segment spaces answer in separate segments. */
  public async currentOutcome(
    identity: RequestIdentity,
    turn: NativeTurn,
  ): Promise<{ outcome?: RunOutcome; message: NativeMessage }> {
    const segments = z
      .array(segmentSchema)
      .parse(await this.unique.getTurnSegments(identity, turn.chatId, turn.userMessageId));
    const turnSegments = segments.length
      ? segments.sort((a, b) => (a.segmentIndex ?? 0) - (b.segmentIndex ?? 0))
      : [segmentSchema.parse(await this.unique.getMessage(identity, turn.chatId, turn.messageId))];
    const answers = turnSegments.filter(
      (segment) => !segment.segmentKind || segment.segmentKind === 'ANSWER',
    );
    const settled = turnSegments.find(
      (segment) =>
        (!segment.segmentKind || TERMINAL_SEGMENT_KINDS.includes(segment.segmentKind)) &&
        (segment.completedAt || segment.stoppedStreamingAt),
    );
    const message: NativeMessage = {
      id: turn.messageId,
      text: answers
        .map((segment) => segment.text)
        .filter(Boolean)
        .join('\n\n'),
      completedAt: settled?.completedAt,
      stoppedStreamingAt: settled?.stoppedStreamingAt,
      userAbortedAt: turnSegments.find((segment) => segment.userAbortedAt)?.userAbortedAt,
      references: answers.flatMap((segment) => segment.references ?? []),
    };
    if (message.userAbortedAt) {
      return { outcome: { kind: 'canceled', message }, message };
    }
    if (message.completedAt) {
      return { outcome: { kind: 'completed', message }, message };
    }
    if (message.stoppedStreamingAt) {
      return { outcome: { kind: 'failed', message }, message };
    }
    const elicitation = await this.pendingElicitation(identity, turn.chatId);
    return elicitation ? { outcome: { kind: 'elicitation', elicitation }, message } : { message };
  }

  public async pendingElicitation(
    identity: RequestIdentity,
    chatId: string,
  ): Promise<PendingElicitation | undefined> {
    const elicitations = z
      .array(elicitationSchema)
      .parse(await this.unique.getChatElicitations(identity, chatId));
    return elicitations
      .filter(
        (elicitation) => elicitation.status === 'PENDING' && elicitation.userId === identity.userId,
      )
      .at(-1);
  }

  public observe(options: ObserveOptions): Promise<RunOutcome> {
    const { identity, turn } = options;
    return new Promise((resolve, reject) => {
      let settled = false;
      let polling = false;
      let lastText = '';
      const finish = (callback: () => void): void => {
        if (!settled) {
          settled = true;
          unsubscribe();
          clearInterval(poller);
          clearInterval(heartbeat);
          clearTimeout(timeout);
          callback();
        }
      };
      const emitText = async (text: string | null | undefined): Promise<void> => {
        if (text && text !== lastText) {
          lastText = text;
          await options.onText?.(text);
        }
      };
      const poll = async (): Promise<void> => {
        if (settled || polling) {
          return;
        }
        polling = true;
        try {
          const { outcome, message } = await this.currentOutcome(identity, turn);
          await emitText(message.text);
          if (outcome) {
            finish(() => resolve(outcome));
          }
        } catch (error) {
          finish(() => reject(error));
        } finally {
          polling = false;
        }
      };
      const unsubscribe = this.events.subscribe(
        identity.companyId,
        turn.messageId,
        async (event) => {
          if (event.type === 'unique.chat.assistant-message.update') {
            if (typeof event.payload.text === 'string') {
              await emitText(event.payload.text);
            }
            if (TERMINAL_EVENT_FIELDS.some((field) => event.payload[field])) {
              await poll();
            }
          } else if (
            event.type === 'unique.chat.assistant-message.finished' ||
            event.type.startsWith('unique.chat.elicitation.')
          ) {
            await poll();
          }
        },
      );
      const poller = setInterval(() => void poll(), POLL_INTERVAL_MS);
      const heartbeat = setInterval(() => {
        Promise.resolve(options.onHeartbeat?.()).catch(() => undefined);
      }, HEARTBEAT_INTERVAL_MS);
      const timeout = setTimeout(() => {
        finish(() => reject(new Error('native execution timed out')));
      }, this.config.streamTimeoutMs);
      void poll();
    });
  }
}
