import { InjectTemporalClient } from '@unique-ag/temporal';
import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { WorkflowClient } from '@temporalio/client';
import { EmailEvents, EmailSavedEvent } from './email.events';

@Injectable()
export class IngestService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@InjectTemporalClient() private readonly temporalClient: WorkflowClient) {}

  @OnEvent(EmailEvents.EmailSaved)
  public async onEmailSaved(event: EmailSavedEvent) {
    // const { userProfileId, emailId } = event;

    // const handle = await this.temporalClient.start('ingest', {
    //   args: [userProfileId.toString(), emailId.toString()],
    //   taskQueue: 'default',
    //   workflowId: `wf-id-${emailId.toString()}-${Math.floor(Math.random() * 1000)}`,
    // });
    // this.logger.log(`Started workflow ${handle.workflowId}`);
  }
}
