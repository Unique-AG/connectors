import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Injectable } from '@nestjs/common';
import { type HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { EVENT_BUS_EXCHANGE } from '../event-bus/event-bus.module.js';

@Injectable()
export class AmqpHealthIndicator {
  public constructor(
    private readonly connection: AmqpConnection,
    private readonly indicators: HealthIndicatorService,
  ) {}

  public async check(): Promise<HealthIndicatorResult> {
    const indicator = this.indicators.check('amqp');
    try {
      if (!this.connection.connected || !this.connection.channel) {
        return indicator.down({ message: 'AMQP is not connected' });
      }
      await this.connection.channel.checkExchange(EVENT_BUS_EXCHANGE);
      return indicator.up();
    } catch (error) {
      return indicator.down({ message: error instanceof Error ? error.message : String(error) });
    }
  }
}
