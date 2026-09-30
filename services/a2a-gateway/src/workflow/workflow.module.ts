import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module.js';
import { MaintenanceService } from './maintenance.service.js';
import { WorkflowService } from './workflow.service.js';

@Module({
  imports: [DrizzleModule],
  providers: [WorkflowService, MaintenanceService],
  exports: [WorkflowService, MaintenanceService],
})
export class WorkflowModule {}
