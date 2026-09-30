import { Module } from '@nestjs/common';
import { ClusterIdentityGuard } from '../auth/identity.guard.js';
import { ChatFilesService } from '../bridge/chat-files.service.js';
import { CredentialsModule } from '../credentials/credentials.module.js';
import { PersistenceModule } from '../drizzle/persistence.module.js';
import { EventBusModule } from '../event-bus/event-bus.module.js';
import { UniqueModule } from '../unique/unique.module.js';
import { WorkflowModule } from '../workflow/workflow.module.js';
import { OutboundController } from './outbound.controller.js';
import { OutboundCancellationListener } from './outbound-cancellation.listener.js';
import { OutboundExecutionService } from './outbound-execution.service.js';
import { OutboundRecovery } from './outbound-recovery.service.js';
import { OutboundRunner } from './outbound-runner.service.js';

@Module({
  imports: [PersistenceModule, UniqueModule, CredentialsModule, WorkflowModule, EventBusModule],
  controllers: [OutboundController],
  providers: [
    ClusterIdentityGuard,
    ChatFilesService,
    OutboundCancellationListener,
    OutboundExecutionService,
    OutboundRecovery,
    OutboundRunner,
  ],
})
export class OutboundModule {}
