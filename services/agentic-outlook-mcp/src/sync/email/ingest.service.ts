import { InjectTemporalClient } from '@unique-ag/temporal';
import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { WorkflowClient } from '@temporalio/client';
import { typeid } from 'typeid-js';
import { EmailEvents, EmailSavedEvent } from './email.events';

@Injectable()
export class IngestService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@InjectTemporalClient() private readonly temporalClient: WorkflowClient) {}

  @OnEvent(EmailEvents.EmailSaved)
  public async onEmailSaved(event: EmailSavedEvent) {
    const { userProfileId, emailId } = event;

    const workflowId = `wf-ingest-${emailId.toString()}-${typeid()}`;

    const handle = await this.temporalClient.start('ingest', {
      args: [userProfileId.toString(), emailId.toString()],
      taskQueue: 'default',
      workflowId,
    });
    this.logger.log(`Started workflow ${handle.workflowId}`);
  }
}
