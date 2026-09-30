import { Module } from '@nestjs/common';
import { ClusterIdentityGuard } from '../auth/identity.guard.js';
import { CredentialsModule } from '../credentials/credentials.module.js';
import { PersistenceModule } from '../drizzle/persistence.module.js';
import { UniqueModule } from '../unique/unique.module.js';
import { WorkflowModule } from '../workflow/workflow.module.js';
import { OutboundController } from './outbound.controller.js';
import { OutboundExecutionService } from './outbound-execution.service.js';
import { OutboundRunner } from './outbound-runner.service.js';

@Module({
  imports: [PersistenceModule, UniqueModule, CredentialsModule, WorkflowModule],
  controllers: [OutboundController],
  providers: [ClusterIdentityGuard, OutboundExecutionService, OutboundRunner],
})
export class OutboundModule {}
