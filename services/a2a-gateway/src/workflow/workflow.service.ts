import {
  Inject,
  Injectable,
  type OnApplicationBootstrap,
  type OnApplicationShutdown,
} from '@nestjs/common';
import { Absurd } from 'absurd-sdk';
import type { Pool } from 'pg';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { POSTGRES_POOL } from '../drizzle/drizzle.module.js';

const OUTBOUND_RUN_TASK = 'outbound.run';
const WORKFLOW_QUEUE = 'a2a-gateway';

@Injectable()
export class WorkflowService implements OnApplicationBootstrap, OnApplicationShutdown {
  private readonly absurd: Absurd;
  private started = false;
  private startupError: Error | undefined;

  public constructor(
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
    @Inject(POSTGRES_POOL) pool: Pool,
  ) {
    this.absurd = new Absurd({ db: pool, queueName: WORKFLOW_QUEUE });
    this.absurd.registerTask<Record<string, never>, { accepted: true }>(
      { name: OUTBOUND_RUN_TASK, defaultMaxAttempts: 5 },
      async () => ({ accepted: true }),
    );
  }

  public async onApplicationBootstrap(): Promise<void> {
    if (!this.config.workerEnabled) {
      return;
    }

    try {
      await this.absurd.startWorker({
        concurrency: this.config.workerConcurrency,
        onError: (error) => {
          this.startupError = error;
        },
      });
      this.started = true;
    } catch (error) {
      this.startupError = error instanceof Error ? error : new Error(String(error));
    }
  }

  public status(): { enabled: boolean; ready: boolean; error?: string } {
    return {
      enabled: this.config.workerEnabled,
      ready: !this.config.workerEnabled || (this.started && !this.startupError),
      ...(this.startupError ? { error: this.startupError.message } : {}),
    };
  }

  public async onApplicationShutdown(): Promise<void> {
    await this.absurd.close();
  }
}
