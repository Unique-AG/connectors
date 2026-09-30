import { Module } from '@nestjs/common';
import { KongIdentityGuard } from '../auth/identity.guard.js';
import { OAuthDiscoveryController } from '../auth/oauth-discovery.controller.js';
import { ChatFilesService } from '../bridge/chat-files.service.js';
import { CredentialsModule } from '../credentials/credentials.module.js';
import { DrizzleModule } from '../drizzle/drizzle.module.js';
import { PersistenceModule } from '../drizzle/persistence.module.js';
import { EventBusModule } from '../event-bus/event-bus.module.js';
import { UniqueModule } from '../unique/unique.module.js';
import { WorkflowModule } from '../workflow/workflow.module.js';
import { A2aController } from './a2a.controller.js';
import { A2aSdkService } from './a2a-sdk.service.js';
import { InboundAdmissionService } from './inbound-admission.service.js';
import { InboundAgentExecutor } from './inbound-agent.executor.js';
import { InboundFilesService } from './inbound-files.service.js';
import { InboundRecovery } from './inbound-recovery.service.js';
import { NativeRunObserver } from './native-run-observer.js';
import { PgPushNotificationStore } from './pg-push-notification.store.js';
import { PublicationService } from './publication.service.js';
import { DurablePushNotificationSender } from './push-notification.sender.js';

@Module({
  imports: [
    DrizzleModule,
    PersistenceModule,
    UniqueModule,
    EventBusModule,
    WorkflowModule,
    CredentialsModule,
  ],
  controllers: [A2aController, OAuthDiscoveryController],
  providers: [
    A2aSdkService,
    ChatFilesService,
    InboundAdmissionService,
    InboundAgentExecutor,
    InboundFilesService,
    InboundRecovery,
    NativeRunObserver,
    PgPushNotificationStore,
    DurablePushNotificationSender,
    KongIdentityGuard,
    PublicationService,
  ],
  exports: [A2aSdkService],
})
export class A2aServerModule {}
