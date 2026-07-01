import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable } from '@nestjs/common';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { HealthConfig, healthConfig } from '~/config';

@Injectable()
export class AmqpHealthIndicator {
  private readonly checkExchangeTimeoutMs: number;

  public constructor(
    private readonly amqpConnection: AmqpConnection,
    @Inject(healthConfig.KEY) config: HealthConfig,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {
    this.checkExchangeTimeoutMs = config.amqpCheckTimeoutMs;
  }

  public async check(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    try {
      if (!this.amqpConnection.connected || !this.amqpConnection.channel) {
        return indicator.down({ message: 'AMQP not connected' });
      }
      let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
      const timeout = new Promise<never>((_, reject) => {
        timeoutHandle = setTimeout(
          () => reject(new Error('AMQP checkExchange timed out')),
          this.checkExchangeTimeoutMs,
        );
      });
      await Promise.race([
        this.amqpConnection.channel
          .checkExchange(MAIN_EXCHANGE.name)
          .finally(() => clearTimeout(timeoutHandle)),
        timeout,
      ]);
      return indicator.up();
    } catch (error) {
      return indicator.down({ message: error instanceof Error ? error.message : String(error) });
    }
  }
}
