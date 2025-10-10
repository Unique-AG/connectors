import { RabbitMQModule } from '@golevelup/nestjs-rabbitmq';
import { Module } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { AppConfig, AppSettings } from '../../app-settings';

@Module({
  imports: [
    RabbitMQModule.forRootAsync({
      useFactory: (configService: ConfigService<AppConfig, true>) => ({
        uri: configService.get(AppSettings.AMQP_URL),
        connectionInitOptions: {
          wait: false,
        },
        exchanges: [
          { name: 'email.pipeline', type: 'topic', options: { durable: true } },
          { name: 'email.pipeline.retry', type: 'topic', options: { durable: true } },
          { name: 'email.pipeline.dlx', type: 'topic', options: { durable: true } },
        ],
        queues: [
          {
            name: 'q.email.ingest',
            exchange: 'email.pipeline',
            routingKey: 'email.ingest',
            options: { durable: true },
          },
          {
            name: 'q.email.ingest.retry',
            exchange: 'email.pipeline.retry',
            routingKey: 'email.ingest.retry',
            options: {
              durable: true,
              deadLetterExchange: 'email.pipeline',
              deadLetterRoutingKey: 'email.ingest',
            },
          },
          {
            name: 'q.email.ingest.dlx',
            exchange: 'email.pipeline.dlx',
            routingKey: 'email.ingest.dlx',
            options: { durable: true },
          },
          // { name: 'q.email.process' },
          // { name: 'q.email.process.retry' },
          // { name: 'q.email.process.dlx' },
          // { name: 'q.email.embed' },
          // { name: 'q.email.embed.retry' },
          // { name: 'q.email.embed.dlx' },
          // { name: 'q.email.index' },
          // { name: 'q.email.index.retry' },
          // { name: 'q.email.index.dlx' },
        ],
        channels: {
          pipeline: {
            prefetchCount: 20,
            default: true,
          },
        },
      }),
      inject: [ConfigService],
    }),
  ],
  providers: [],
  exports: [RabbitMQModule],
})
export class AmqpModule {}
