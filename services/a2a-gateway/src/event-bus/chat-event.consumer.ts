import { hostname } from 'node:os';
import { RabbitSubscribe } from '@golevelup/nestjs-rabbitmq';
import { Injectable } from '@nestjs/common';
import { z } from 'zod';
import { EVENT_BUS_EXCHANGE } from './event-bus.constants.js';

const eventSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.enum([
      'unique.chat.assistant-message.created',
      'unique.chat.assistant-message.update',
      'unique.chat.assistant-message.stream.chunk',
      'unique.chat.assistant-message.finished',
    ]),
    companyId: z.string(),
    userId: z.string(),
    messageId: z.string(),
    chatId: z.string(),
    payload: z.record(z.string(), z.unknown()).default({}),
  }),
  z.object({
    type: z.enum([
      'unique.chat.elicitation.created',
      'unique.chat.elicitation.responded',
      'unique.chat.elicitation.expired',
    ]),
    companyId: z.string(),
    userId: z.string(),
    messageId: z.string(),
    elicitationId: z.string(),
    payload: z.record(z.string(), z.unknown()).default({}),
  }),
]);

export type ChatEvent = z.infer<typeof eventSchema>;
type ChatEventListener = (event: ChatEvent) => void | Promise<void>;

@Injectable()
export class ChatEventConsumer {
  private readonly listeners = new Map<string, Set<ChatEventListener>>();

  public subscribe(companyId: string, messageId: string, listener: ChatEventListener): () => void {
    const key = `${companyId}:${messageId}`;
    const listeners = this.listeners.get(key) ?? new Set<ChatEventListener>();
    listeners.add(listener);
    this.listeners.set(key, listeners);
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) {
        this.listeners.delete(key);
      }
    };
  }

  @RabbitSubscribe({
    exchange: EVENT_BUS_EXCHANGE,
    routingKey: 'unique.chat.#',
    queue: `a2a-gateway.${hostname()}`,
    queueOptions: { durable: false, autoDelete: true },
  })
  public async consume(payload: unknown): Promise<void> {
    const parsed = eventSchema.safeParse(payload);
    if (!parsed.success) {
      return;
    }
    const event = parsed.data;
    const listeners = this.listeners.get(`${event.companyId}:${event.messageId}`) ?? [];
    await Promise.all([...listeners].map((listener) => listener(event)));
  }
}
