import {
  Inject,
  Injectable,
  Logger,
  type OnApplicationBootstrap,
  type OnApplicationShutdown,
} from '@nestjs/common';
import {
  Absurd,
  type JsonValue,
  type SpawnOptions,
  type SpawnResult,
  type TaskContext,
} from 'absurd-sdk';
import type { Pool } from 'pg';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { POSTGRES_POOL } from '../drizzle/drizzle.module.js';

const WORKFLOW_QUEUE = 'a2a-gateway';

export type WorkflowHandler<P> = (
  params: P,
  context: TaskContext,
) => Promise<JsonValue | undefined>;

/**
 * Owns the absurd client. Feature modules register their tasks while the application initialises;
 * the worker starts on bootstrap, so every registration exists before the first claim.
 */
@Injectable()
export class WorkflowService implements OnApplicationBootstrap, OnApplicationShutdown {
  private readonly logger = new Logger(WorkflowService.name);
  private readonly absurd: Absurd;
  private started = false;
  private startupError: Error | undefined;

  public constructor(
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
    @Inject(POSTGRES_POOL) pool: Pool,
  ) {
    this.absurd = new Absurd({ db: pool, queueName: WORKFLOW_QUEUE });
  }

  public register<P>(
    name: string,
    handler: WorkflowHandler<P>,
    options: { defaultMaxAttempts?: number } = {},
  ): void {
    this.absurd.registerTask<P, JsonValue | undefined>(
      { name, defaultMaxAttempts: options.defaultMaxAttempts ?? 5 },
      (params, context) => handler(params, context),
    );
  }

  public spawn<P extends JsonValue>(
    name: string,
    params: P,
    options: SpawnOptions = {},
  ): Promise<SpawnResult> {
    return this.absurd.spawn(name, params, options);
  }

  /** Event payloads are immutable per name, so event names must identify one occurrence. */
  public emitEvent(name: string, payload?: JsonValue): Promise<void> {
    return this.absurd.emitEvent(name, payload);
  }

  public async onApplicationBootstrap(): Promise<void> {
    if (!this.config.workerEnabled) {
      return;
    }
    try {
      await this.absurd.startWorker({
        concurrency: this.config.workerConcurrency,
        onError: (error) => {
          this.logger.error({ msg: 'workflow task failed', err: error.message });
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
