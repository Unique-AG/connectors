import { RabbitMQModule } from '@golevelup/nestjs-rabbitmq';
import { Global, Module } from '@nestjs/common';
import { type AMQPConfig, amqpConfig } from '../config';
import { DEAD_EXCHANGE, DEAD_QUEUE, MAIN_EXCHANGE } from './amqp.constants';
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
          enableControllerDiscovery: true,
          // We set the default prefetch count is 7 because usually have bulky messages so for full sync if
          // we process 7 messages asyncronosly it can result in: 7 * 100 * 4 = 2800 calls to
          // unique in async mode we should limit the prefetching to not overhelm ourselves
          // and also to not overhelm unique.
          prefetchCount: 7,
          // NOTE: (de)serialisation for empty messages doesn't work well with OTEL & json parsing
        };
      },
    }),
  ],
  providers: [AMQPService],
  exports: [RabbitMQModule],
})
export class AMQPModule {}
