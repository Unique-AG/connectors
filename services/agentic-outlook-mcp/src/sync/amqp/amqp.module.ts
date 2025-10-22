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
          { name: 'email.orchestrator', type: 'direct', options: { durable: true } },
        ],
        queues: [
          // Pipeline queues
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
            name: 'q.email.process',
            exchange: 'email.pipeline',
            routingKey: 'email.process',
            options: { durable: true },
          },
          {
            name: 'q.email.process.retry',
            exchange: 'email.pipeline.retry',
            routingKey: 'email.process.retry',
            options: {
              durable: true,
              deadLetterExchange: 'email.pipeline',
              deadLetterRoutingKey: 'email.process',
            },
          },
          {
            name: 'q.email.embed',
            exchange: 'email.pipeline',
            routingKey: 'email.embed',
            options: { durable: true },
          },
          {
            name: 'q.email.embed.retry',
            exchange: 'email.pipeline.retry',
            routingKey: 'email.embed.retry',
            options: {
              durable: true,
              deadLetterExchange: 'email.pipeline',
              deadLetterRoutingKey: 'email.embed',
            },
          },
          // { name: 'q.email.index' },
          // { name: 'q.email.index.retry' },
          // Single orchestrator queue for all events
          {
            name: 'q.orchestrator',
            exchange: 'email.orchestrator',
            routingKey: 'orchestrator',
            options: { durable: true },
          },
          {
            name: 'q.orchestrator.retry',
            exchange: 'email.orchestrator',
            routingKey: 'orchestrator.retry',
            options: {
              durable: true,
              deadLetterExchange: 'email.orchestrator',
              deadLetterRoutingKey: 'orchestrator',
            },
          },
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
