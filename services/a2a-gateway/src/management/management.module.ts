import { Module } from '@nestjs/common';
import { KongIdentityGuard } from '../auth/identity.guard.js';
import { PersistenceModule } from '../drizzle/persistence.module.js';
import { UniqueModule } from '../unique/unique.module.js';
import { ManagementController } from './management.controller.js';
import { ManagementService } from './management.service.js';

@Module({
  imports: [PersistenceModule, UniqueModule],
  controllers: [ManagementController],
  providers: [KongIdentityGuard, ManagementService],
})
export class ManagementModule {}
