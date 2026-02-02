import { InjectTemporalClient } from '@unique-ag/temporal';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { WorkflowClient } from '@temporalio/client';
import { and, eq } from 'drizzle-orm';
import { TypeID, typeid } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, emails as emailsTable } from '../../drizzle';
import { EmailEvents, EmailSavedEvent } from './email.events';

@Injectable()
export class IngestService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectTemporalClient() private readonly temporalClient: WorkflowClient,
  ) {}

  @OnEvent(EmailEvents.EmailSaved)
  public async onEmailSaved(event: EmailSavedEvent) {
    const { userProfileId, emailId } = event;

    const workflowId = `wf-ingest-${emailId.toString()}-${typeid()}`;

    const handle = await this.temporalClient.start('ingest', {
      args: [{ userProfileId: userProfileId.toString(), emailId: emailId.toString() }],
      taskQueue: 'default',
      workflowId,
    });
    this.logger.log(`Started workflow ${handle.workflowId}`);
  }

  public async reprocessEmail(userProfileId: TypeID<'user_profile'>, emailId: TypeID<'email'>) {
    this.logger.log({ msg: 'Reprocessing email', userProfileId, emailId });

    const email = await this.db.query.emails.findFirst({
      where: and(
        eq(emailsTable.id, emailId.toString()),
        eq(emailsTable.userProfileId, userProfileId.toString()),
      ),
    });

    if (!email) throw new Error(`Email not found: ${emailId}`);

    const workflowId = `wf-reprocess-${emailId.toString()}-${typeid()}`;

    const handle = await this.temporalClient.start('ingest', {
      args: [{ userProfileId: userProfileId.toString(), emailId: emailId.toString() }],
      taskQueue: 'default',
      workflowId,
    });

    this.logger.log({
      msg: 'Started reprocess workflow',
      workflowId: handle.workflowId,
      userProfileId,
      emailId,
    });
  }
}
