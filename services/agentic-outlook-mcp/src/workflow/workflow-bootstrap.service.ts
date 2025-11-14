import { WorkflowRuntime } from '@dapr/dapr';
import { Injectable, Logger, OnApplicationBootstrap } from '@nestjs/common';

@Injectable()
export class WorkflowBootstrapService implements OnApplicationBootstrap {
  private readonly logger = new Logger(this.constructor.name);
  public constructor(private readonly runtime: WorkflowRuntime) {}

  public async onApplicationBootstrap() {
    this.logger.log('Starting workflow runtime...');
    try {
      await this.runtime.start();
      this.logger.log('Workflow runtime started successfully');
    } catch (error) {
      this.logger.error('Failed to start workflow runtime', error);
      throw error;
    }
  }
}
