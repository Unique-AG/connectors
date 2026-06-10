import { RabbitMQModule } from '@golevelup/nestjs-rabbitmq';
import { Global, Module } from '@nestjs/common';
import { type AMQPConfig, amqpConfig } from '../config';
import { DEAD_EXCHANGE, DEAD_QUEUE, INGESTION_CHANNEL, MAIN_EXCHANGE } from './amqp.constants';
import { AMQPService } from './amqp.service';

@Global()
@Module({
  imports: [
    RabbitMQModule.forRootAsync({
      inject: [amqpConfig.KEY],
      useFactory(config: AMQPConfig) {
        return {
          uri: config.url.value.toString(),
          connectionInitOptions: { wait: false },
          exchanges: [MAIN_EXCHANGE, DEAD_EXCHANGE],
          queues: [DEAD_QUEUE],
          // Bound the ingestion consumer to one in-flight message so only one recording is
          // disk-spooled at a time (see INGESTION_CHANNEL).
          channels: { [INGESTION_CHANNEL]: { prefetchCount: 1 } },
          enableControllerDiscovery: true,
          // NOTE: (de)serialisation for empty messages doesn't work well with OTEL & json parsing
        };
      },
    }),
  ],
  providers: [AMQPService],
  exports: [RabbitMQModule],
})
export class AMQPModule {}
