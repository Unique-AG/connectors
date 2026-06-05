import { type RabbitMQExchangeConfig, type RabbitMQQueueConfig } from '@golevelup/nestjs-rabbitmq';

export const MAIN_EXCHANGE = {
  name: 'unique.teams-mcp.main',
  type: 'topic',
  options: { durable: true },
  createExchangeIfNotExists: true,
} as const satisfies RabbitMQExchangeConfig;

export const DEAD_EXCHANGE = {
  name: 'unique.teams-mcp.dead',
  type: 'topic',
  options: { durable: true },
  createExchangeIfNotExists: true,
} as const satisfies RabbitMQExchangeConfig;

export const DEAD_QUEUE = {
  name: 'unique.teams-mcp.dead',
  exchange: DEAD_EXCHANGE.name,
  routingKey: '#',
  createQueueIfNotExists: true,
} as const satisfies RabbitMQQueueConfig;

/**
 * Dedicated channel for transcript/recording ingestion, pinned to `prefetchCount: 1`.
 * Ingestion buffers the full recording in memory before uploading, so processing one message at a
 * time bounds peak memory to a single recording and prevents concurrent large uploads from
 * OOM-killing the (singleton) pod. Lifecycle/subscription events stay on the default channel.
 */
export const INGESTION_CHANNEL = 'unique.teams-mcp.ingestion';
