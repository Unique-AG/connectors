import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module.js';
import { PersistenceModule } from '../drizzle/persistence.module.js';
import { RetentionRepository } from '../drizzle/retention.repository.js';
import { UniqueModule } from '../unique/unique.module.js';
import { WorkflowModule } from '../workflow/workflow.module.js';
import { LifecycleService } from './lifecycle.service.js';

@Module({
  imports: [DrizzleModule, PersistenceModule, UniqueModule, WorkflowModule],
  providers: [LifecycleService, RetentionRepository],
})
export class LifecycleModule {}
