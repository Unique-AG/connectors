import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module.js';
import { WorkflowService } from './workflow.service.js';

@Module({
  imports: [DrizzleModule],
  providers: [WorkflowService],
  exports: [WorkflowService],
})
export class WorkflowModule {}
