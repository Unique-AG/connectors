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
