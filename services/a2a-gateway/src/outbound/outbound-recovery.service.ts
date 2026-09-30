import { Injectable, Logger, type OnModuleInit } from '@nestjs/common';
import { ExecutionRepository } from '../drizzle/execution.repository.js';
import { MaintenanceService } from '../workflow/maintenance.service.js';
import { WorkflowService } from '../workflow/workflow.service.js';
import {
  OUTBOUND_RUN_OPTIONS,
  OUTBOUND_RUN_TASK,
  type OutboundRunParams,
} from './outbound-execution.service.js';
import { OutboundRunner } from './outbound-runner.service.js';

const STALE_AFTER_MS = 2 * 60_000;
const MAX_RECOVERIES = 3;
const LIVE_TASK_STATES = ['pending', 'running', 'sleeping'];

/**
 * Restarts runs whose durable task ended without settling the execution (retries exhausted, lost
 * worker). A restarted run resumes from the recorded remote task and never re-sends the turn.
 */
@Injectable()
export class OutboundRecovery implements OnModuleInit {
  private readonly logger = new Logger(OutboundRecovery.name);

  public constructor(
    private readonly executions: ExecutionRepository,
    private readonly maintenance: MaintenanceService,
    private readonly runner: OutboundRunner,
    private readonly workflow: WorkflowService,
  ) {}

  public onModuleInit(): void {
    this.maintenance.register('outbound.recover', () => this.recover());
  }

  public async recover(): Promise<void> {
    const stale = await this.executions.findStale(new Date(Date.now() - STALE_AFTER_MS));
    for (const execution of stale) {
      const state = execution.workflowTaskId
        ? await this.workflow.taskState(execution.workflowTaskId)
        : undefined;
      if (state && LIVE_TASK_STATES.includes(state)) {
        continue;
      }
      if (execution.recoveries >= MAX_RECOVERIES) {
        await this.runner.abandon(execution);
        continue;
      }
      const params: OutboundRunParams = {
        executionId: execution.id,
        companyId: execution.companyId,
        userId: execution.userId,
      };
      const { taskID } = await this.workflow.spawn(OUTBOUND_RUN_TASK, params, {
        ...OUTBOUND_RUN_OPTIONS,
        idempotencyKey: `${execution.id}:recover:${execution.recoveries + 1}`,
      });
      await this.executions.recordRecovery(execution.companyId, execution.id, taskID);
      this.logger.warn({
        action: 'execution.recover',
        companyId: execution.companyId,
        executionId: execution.id,
        previousTaskState: state ?? 'missing',
      });
    }
  }
}
