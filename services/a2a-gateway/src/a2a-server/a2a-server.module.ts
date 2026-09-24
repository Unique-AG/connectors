import { Module } from '@nestjs/common';
import { KongIdentityGuard } from '../auth/identity.guard.js';
import { OAuthDiscoveryController } from '../auth/oauth-discovery.controller.js';
import { PersistenceModule } from '../drizzle/persistence.module.js';
import { EventBusModule } from '../event-bus/event-bus.module.js';
import { UniqueModule } from '../unique/unique.module.js';
import { A2aController } from './a2a.controller.js';
import { A2aSdkService } from './a2a-sdk.service.js';
import { InboundAgentExecutor } from './inbound-agent.executor.js';
import { PublicationService } from './publication.service.js';

@Module({
  imports: [PersistenceModule, UniqueModule, EventBusModule],
  controllers: [A2aController, OAuthDiscoveryController],
  providers: [A2aSdkService, InboundAgentExecutor, KongIdentityGuard, PublicationService],
  exports: [A2aSdkService],
})
export class A2aServerModule {}
