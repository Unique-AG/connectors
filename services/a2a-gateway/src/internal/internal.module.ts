import { Module } from '@nestjs/common';
import { ClusterIdentityGuard } from '../auth/identity.guard.js';
import { PersistenceModule } from '../drizzle/persistence.module.js';
import { InternalController } from './internal.controller.js';
import { InternalService } from './internal.service.js';

@Module({
  imports: [PersistenceModule],
  controllers: [InternalController],
  providers: [ClusterIdentityGuard, InternalService],
})
export class InternalModule {}
