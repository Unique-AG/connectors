import { Injectable } from '@nestjs/common';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';

@Injectable()
export class AmqpHealthIndicator {
  public constructor(
    private readonly amqpConnection: AmqpConnection,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {}

  public async check(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    try {
      if (!this.amqpConnection.connected || !this.amqpConnection.channel) {
        return indicator.down({ message: 'AMQP not connected' });
      }
      await this.amqpConnection.channel.checkExchange(MAIN_EXCHANGE.name);
      return indicator.up();
    } catch (error) {
      return indicator.down({ message: String(error) });
    }
  }
}
