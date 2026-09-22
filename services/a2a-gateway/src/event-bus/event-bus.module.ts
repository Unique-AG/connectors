import { RabbitMQModule } from '@golevelup/nestjs-rabbitmq';
import { Module } from '@nestjs/common';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';

export const EVENT_BUS_EXCHANGE = 'unique.event-bus';

@Module({
  imports: [
    RabbitMQModule.forRootAsync({
      inject: [GATEWAY_CONFIG],
      useFactory: (config: GatewayConfig) => ({
        uri: config.amqpUrl.toString(),
        connectionInitOptions: { wait: false },
        exchanges: [{ name: EVENT_BUS_EXCHANGE, type: 'topic', createExchangeIfNotExists: false }],
        enableControllerDiscovery: true,
      }),
    }),
  ],
  exports: [RabbitMQModule],
})
export class EventBusModule {}
