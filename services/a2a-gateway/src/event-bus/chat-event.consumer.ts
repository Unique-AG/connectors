import { hostname } from 'node:os';
import { RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { z } from 'zod';
import { EVENT_BUS_EXCHANGE } from './event-bus.constants.js';

// node-chat publishes `{ messageType, message: { event, id, userId?, companyId?, payload } }`.
const envelopeSchema = z.object({
  message: z.object({
    event: z.string().startsWith('unique.chat.'),
    companyId: z.string().min(1),
    userId: z.string().nullish(),
    payload: z.record(z.string(), z.unknown()).default({}),
  }),
});

export interface ChatEvent {
  type: string;
  companyId: string;
  userId?: string;
  messageId?: string;
  chatId?: string;
  payload: Record<string, unknown>;
}

type ChatEventListener = (event: ChatEvent) => void | Promise<void>;

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

/**
 * Per-replica, auto-deleted queue on the platform event bus. Events only trigger re-reads of
 * core state; they are never an identity source and are always scoped by companyId.
 */
@Injectable()
export class ChatEventConsumer {
  private readonly logger = new Logger(ChatEventConsumer.name);
  private readonly messageListeners = new Map<string, Set<ChatEventListener>>();
  private readonly globalListeners = new Set<ChatEventListener>();

  public subscribe(companyId: string, messageId: string, listener: ChatEventListener): () => void {
    const key = `${companyId}:${messageId}`;
    const listeners = this.messageListeners.get(key) ?? new Set<ChatEventListener>();
    listeners.add(listener);
    this.messageListeners.set(key, listeners);
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) {
        this.messageListeners.delete(key);
      }
    };
  }

  public onEvent(listener: ChatEventListener): () => void {
    this.globalListeners.add(listener);
    return () => this.globalListeners.delete(listener);
  }

  @RabbitSubscribe({
    exchange: EVENT_BUS_EXCHANGE,
    routingKey: 'unique.chat.#',
    queue: `a2a-gateway.${hostname()}`,
    queueOptions: { durable: false, autoDelete: true },
  })
  public async consume(payload: unknown): Promise<void> {
    const parsed = envelopeSchema.safeParse(payload);
    if (!parsed.success) {
      return;
    }
    const { event: type, companyId, userId, payload: body } = parsed.data.message;
    const event: ChatEvent = {
      type,
      companyId,
      userId: userId ?? undefined,
      messageId: optionalString(body.messageId),
      chatId: optionalString(body.chatId),
      payload: body,
    };
    const listeners = [
      ...this.globalListeners,
      ...(event.messageId
        ? (this.messageListeners.get(`${companyId}:${event.messageId}`) ?? [])
        : []),
    ];
    await Promise.all(
      listeners.map(async (listener) => {
        try {
          await listener(event);
        } catch (error) {
          this.logger.warn({ msg: 'chat event listener failed', type, err: error });
        }
      }),
    );
  }
}
