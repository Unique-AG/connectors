import { type RabbitMQExchangeConfig, type RabbitMQQueueConfig } from '@golevelup/nestjs-rabbitmq';

// Dedicated channel for ingestion (transcript/recording change-notification) consumers, bound to
// `prefetchCount: 1` so at most one meeting is ingested at a time. With disk-spooled uploads this
// bounds temp-disk usage to a single recording and avoids parallel metered MS Graph downloads.
export const INGESTION_CHANNEL = 'ingestion';

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
