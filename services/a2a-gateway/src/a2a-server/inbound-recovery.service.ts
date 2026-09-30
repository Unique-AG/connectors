import { type Task, TaskState } from '@a2a-js/sdk';
import { Inject, Injectable, Logger, type OnModuleInit } from '@nestjs/common';
import type { JsonObject, TaskContext } from 'absurd-sdk';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { MaintenanceService } from '../workflow/maintenance.service.js';
import { WorkflowService } from '../workflow/workflow.service.js';
import {
  failedStatus,
  fileUrlFor,
  isTerminal,
  outcomeArtifacts,
  outcomeStatus,
  taskStatus,
  textArtifact,
} from './inbound-translation.js';
import { NativeRunObserver } from './native-run-observer.js';
import { PgTaskStore } from './pg-task.store.js';

const INBOUND_WATCH_TASK = 'inbound.watch';
const ORPHANED_AFTER_MS = 90_000;
const SNAPSHOT_INTERVAL_MS = 1_000;

interface InboundWatchParams extends JsonObject {
  taskId: string;
  companyId: string;
  userId: string;
  chatId: string;
  userMessageId: string;
  messageId: string;
  publicationId: string;
}

const UNKNOWN_STATE =
  'The gateway was interrupted before the request reached the space; its state is unknown. Send it again if needed.';

/**
 * Adopts inbound tasks whose executor died (restart, lost replica): the native turn is followed
 * from core and the durable snapshot is updated, so GetTask and SubscribeToTask see the real
 * outcome. The native turn is never started twice.
 */
@Injectable()
export class InboundRecovery implements OnModuleInit {
  private readonly logger = new Logger(InboundRecovery.name);

  public constructor(
    private readonly maintenance: MaintenanceService,
    private readonly observer: NativeRunObserver,
    private readonly taskStore: PgTaskStore,
    private readonly workflow: WorkflowService,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public onModuleInit(): void {
    this.maintenance.register('inbound.recover', () => this.recover());
    this.workflow.register<InboundWatchParams>(INBOUND_WATCH_TASK, (params, context) =>
      this.watch(params, context),
    );
  }

  public async recover(): Promise<void> {
    const orphans = await this.taskStore.findOrphaned(new Date(Date.now() - ORPHANED_AFTER_MS));
    for (const orphan of orphans) {
      const snapshot = orphan.snapshot as unknown as Task;
      if (!orphan.assistantMessageId || !orphan.chatId) {
        await this.taskStore.systemSave(orphan.companyId, {
          ...snapshot,
          status: failedStatus(snapshot, UNKNOWN_STATE),
        });
        this.logger.warn({
          action: 'task.recover-unknown',
          companyId: orphan.companyId,
          taskId: orphan.id,
        });
        continue;
      }
      await this.taskStore.heartbeat(orphan.companyId, orphan.id);
      const params: InboundWatchParams = {
        taskId: orphan.id,
        companyId: orphan.companyId,
        userId: orphan.userId,
        chatId: orphan.chatId,
        userMessageId: orphan.userMessageId,
        messageId: orphan.assistantMessageId,
        publicationId: orphan.publicationId,
      };
      await this.workflow.spawn(INBOUND_WATCH_TASK, params, {
        idempotencyKey: `${orphan.id}:watch:${Math.floor(Date.now() / ORPHANED_AFTER_MS)}`,
        maxAttempts: 3,
      });
      this.logger.warn({ action: 'task.recover', companyId: orphan.companyId, taskId: orphan.id });
    }
  }

  private async watch(params: InboundWatchParams, context: TaskContext) {
    const identity = { companyId: params.companyId, userId: params.userId, roles: [] };
    const snapshot = await this.taskStore.findSnapshot(params.companyId, params.taskId);
    if (!snapshot || isTerminal(snapshot)) {
      return { state: 'settled' };
    }
    let lastSnapshotAt = 0;
    const outcome = await this.observer.observe({
      identity,
      turn: {
        chatId: params.chatId,
        userMessageId: params.userMessageId,
        messageId: params.messageId,
      },
      onText: async (text) => {
        if (Date.now() - lastSnapshotAt < SNAPSHOT_INTERVAL_MS) {
          return;
        }
        lastSnapshotAt = Date.now();
        await this.taskStore.systemSave(params.companyId, {
          ...snapshot,
          status: taskStatus(TaskState.TASK_STATE_WORKING),
          artifacts: [textArtifact(snapshot.id, text)],
        });
      },
      onHeartbeat: async () => {
        await context.heartbeat();
        await this.taskStore.heartbeat(params.companyId, params.taskId);
      },
    });
    await this.taskStore.systemSave(params.companyId, {
      ...snapshot,
      status: outcomeStatus(snapshot, outcome),
      artifacts: outcomeArtifacts(
        snapshot.id,
        outcome,
        fileUrlFor(this.config.publicBaseUrl, params.publicationId, snapshot.id),
      ),
    });
    return { state: outcome.kind };
  }
}
