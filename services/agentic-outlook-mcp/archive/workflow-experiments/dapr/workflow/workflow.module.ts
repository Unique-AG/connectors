import { DaprWorkflowClient, WorkflowRuntime } from '@dapr/dapr';
import { Global, Module } from '@nestjs/common';
import { WorkflowBootstrapService } from './workflow-bootstrap.service';

@Global()
@Module({
  imports: [],
  providers: [
    {
      provide: WorkflowRuntime,
      useValue: new WorkflowRuntime(),
    },
    {
      provide: DaprWorkflowClient,
      useValue: new DaprWorkflowClient(),
    },
    WorkflowBootstrapService,
  ],

  exports: [WorkflowRuntime, DaprWorkflowClient],
})
export class WorkflowModule {}
