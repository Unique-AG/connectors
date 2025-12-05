import { type RabbitMQExchangeConfig } from '@golevelup/nestjs-rabbitmq';

export const AMQP_EXCHANGE = {
  name: 'unique.teams-mcp.main',
  type: 'topic',
  options: { durable: true },
  createExchangeIfNotExists: true,
} as const satisfies RabbitMQExchangeConfig;
