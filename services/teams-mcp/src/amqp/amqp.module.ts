import { RabbitMQModule } from '@golevelup/nestjs-rabbitmq';
import { Global, Module } from '@nestjs/common';
import { type AMQPConfig, amqpConfig } from '../config';
import { AMQP_EXCHANGE } from './amqp.constants';
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
          exchanges: [AMQP_EXCHANGE],
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
