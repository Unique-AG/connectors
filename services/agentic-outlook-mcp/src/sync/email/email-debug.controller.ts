import { InjectTemporalClient } from '@unique-ag/temporal';
import { Body, Controller, HttpCode, HttpStatus, Logger, Post } from '@nestjs/common';
import { WorkflowClient } from '@temporalio/client';

interface TriggerIngestDto {
  userProfileId: string;
  emailId: string;
}

@Controller('debug/email')
export class EmailDebugController {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@InjectTemporalClient() private readonly temporalClient: WorkflowClient) {}

  @Post('trigger-ingest')
  @HttpCode(HttpStatus.ACCEPTED)
  public async triggerIngest(@Body() dto: TriggerIngestDto) {
    const { userProfileId, emailId } = dto;

    const workflowId = `debug-wf-${emailId}-${Date.now()}`;

    const handle = await this.temporalClient.start('ingest', {
      args: [userProfileId, emailId],
      taskQueue: 'default',
      workflowId,
    });

    this.logger.log({
      msg: 'Debug: Started ingest workflow',
      workflowId: handle.workflowId,
      userProfileId,
      emailId,
    });

    return {
      success: true,
      workflowId: handle.workflowId,
      userProfileId,
      emailId,
      temporalUi: `http://localhost:8233/namespaces/default/workflows/${handle.workflowId}`,
    };
  }
}

