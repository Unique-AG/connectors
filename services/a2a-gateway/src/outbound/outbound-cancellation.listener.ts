import { Injectable, type OnModuleDestroy, type OnModuleInit } from '@nestjs/common';
import { ExecutionRepository } from '../drizzle/execution.repository.js';
import { type ChatEvent, ChatEventConsumer } from '../event-bus/chat-event.consumer.js';
import { AuditLog } from '../observability/audit-log.service.js';

const MESSAGE_UPDATE = 'unique.chat.assistant-message.update';

/**
 * Turns a user stop in Unique into a cancel request for the executions answering that message,
 * or delegated from it by a parent agent turn. The runner then cancels remotely.
 */
@Injectable()
export class OutboundCancellationListener implements OnModuleInit, OnModuleDestroy {
  private unsubscribe: (() => void) | undefined;

  public constructor(
    private readonly events: ChatEventConsumer,
    private readonly executions: ExecutionRepository,
    private readonly audit: AuditLog,
  ) {}

  public onModuleInit(): void {
    this.unsubscribe = this.events.onEvent((event) => this.handle(event));
  }

  public onModuleDestroy(): void {
    this.unsubscribe?.();
  }

  private async handle(event: ChatEvent): Promise<void> {
    if (event.type !== MESSAGE_UPDATE || !event.messageId || !event.payload.userAbortedAt) {
      return;
    }
    const executions = await this.executions.findActiveForMessage(event.companyId, event.messageId);
    for (const execution of executions) {
      if (await this.executions.requestCancel(event.companyId, execution.id)) {
        this.audit.record(
          'execution.cancel',
          { companyId: event.companyId },
          {
            executionId: execution.id,
          },
        );
      }
    }
  }
}
