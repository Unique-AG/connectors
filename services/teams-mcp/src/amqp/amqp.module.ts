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
          // Ingestion buffers full recordings in memory; pin its channel to one in-flight message
          // so concurrent uploads can't OOM the pod. Other handlers use the default channel.
          channels: {
            [INGESTION_CHANNEL]: { prefetchCount: 1 },
          },
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
