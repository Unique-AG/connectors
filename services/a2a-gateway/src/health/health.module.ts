import { Module } from '@nestjs/common';
import { TerminusModule } from '@nestjs/terminus';
import { DrizzleModule } from '../drizzle/drizzle.module.js';
import { EventBusModule } from '../event-bus/event-bus.module.js';
import { WorkflowModule } from '../workflow/workflow.module.js';
import { AmqpHealthIndicator } from './amqp-health.indicator.js';
import { CoreHealthIndicator } from './core-health.indicator.js';
import { DatabaseHealthIndicator } from './database-health.indicator.js';
import { HealthController } from './health.controller.js';
import { WorkflowHealthIndicator } from './workflow-health.indicator.js';

@Module({
  imports: [TerminusModule, DrizzleModule, EventBusModule, WorkflowModule],
  controllers: [HealthController],
  providers: [
    DatabaseHealthIndicator,
    AmqpHealthIndicator,
    CoreHealthIndicator,
    WorkflowHealthIndicator,
  ],
})
export class HealthModule {}
