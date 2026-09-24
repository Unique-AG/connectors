import { Injectable } from '@nestjs/common';
import { type HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { WorkflowService } from '../workflow/workflow.service.js';

@Injectable()
export class WorkflowHealthIndicator {
  public constructor(
    private readonly workflow: WorkflowService,
    private readonly indicators: HealthIndicatorService,
  ) {}

  public check(): HealthIndicatorResult {
    const indicator = this.indicators.check('worker');
    const status = this.workflow.status();
    return status.ready ? indicator.up({ enabled: status.enabled }) : indicator.down(status);
  }
}
