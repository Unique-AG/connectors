import { Module } from '@nestjs/common';
import { KongIdentityGuard } from '../auth/identity.guard.js';
import { CredentialsModule } from '../credentials/credentials.module.js';
import { PersistenceModule } from '../drizzle/persistence.module.js';
import { UniqueModule } from '../unique/unique.module.js';
import { ConnectionController } from './connection.controller.js';
import { ManagementController } from './management.controller.js';
import { ManagementService } from './management.service.js';

@Module({
  imports: [PersistenceModule, UniqueModule, CredentialsModule],
  controllers: [ManagementController, ConnectionController],
  providers: [KongIdentityGuard, ManagementService],
})
export class ManagementModule {}
