import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Injectable } from '@nestjs/common';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';

const CHECK_EXCHANGE_TIMEOUT_MS = 5_000;

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
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(
          () => reject(new Error('AMQP checkExchange timed out')),
          CHECK_EXCHANGE_TIMEOUT_MS,
        ),
      );
      await Promise.race([this.amqpConnection.channel.checkExchange(MAIN_EXCHANGE.name), timeout]);
      return indicator.up();
    } catch (error) {
      return indicator.down({ message: error instanceof Error ? error.message : String(error) });
    }
  }
}
