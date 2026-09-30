import {
  Inject,
  Injectable,
  Logger,
  type OnApplicationBootstrap,
  type OnModuleInit,
} from '@nestjs/common';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { WorkflowService } from './workflow.service.js';

const MAINTENANCE_TASK = 'maintenance.tick';

type MaintenanceJob = () => Promise<void>;

/**
 * A replica-independent periodic loop on absurd: every interval boundary is one task, deduplicated
 * by its idempotency key, so any number of replicas schedules each tick exactly once.
 */
@Injectable()
export class MaintenanceService implements OnModuleInit, OnApplicationBootstrap {
  private readonly logger = new Logger(MaintenanceService.name);
  private readonly jobs = new Map<string, MaintenanceJob>();

  public constructor(
    private readonly workflow: WorkflowService,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public register(name: string, job: MaintenanceJob): void {
    this.jobs.set(name, job);
  }

  public onModuleInit(): void {
    this.workflow.register<{ runAt: number }>(
      MAINTENANCE_TASK,
      async ({ runAt }, context) => {
        await context.sleepUntil('start', new Date(runAt));
        await this.schedule(this.nextRunAt(runAt));
        for (const [name, job] of this.jobs) {
          try {
            await job();
          } catch (error) {
            this.logger.error({ msg: 'maintenance job failed', job: name, err: error });
          }
        }
        return { runAt };
      },
      { defaultMaxAttempts: 1 },
    );
  }

  public async onApplicationBootstrap(): Promise<void> {
    if (this.config.workerEnabled) {
      await this.schedule(this.nextRunAt(Date.now()));
    }
  }

  private async schedule(runAt: number): Promise<void> {
    await this.workflow.spawn(
      MAINTENANCE_TASK,
      { runAt },
      { idempotencyKey: `maintenance:${runAt}`, maxAttempts: 1 },
    );
  }

  // The next interval boundary in the future, so a changed interval or a long outage never
  // produces a backlog of ticks.
  private nextRunAt(after: number): number {
    const interval = this.intervalMs();
    return (Math.floor(Math.max(after, Date.now()) / interval) + 1) * interval;
  }

  private intervalMs(): number {
    return this.config.reconcileIntervalSeconds * 1000;
  }
}
