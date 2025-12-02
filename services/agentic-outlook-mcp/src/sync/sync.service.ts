import { InjectTemporalClient } from '@unique-ag/temporal';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { WorkflowClient } from '@temporalio/client';
import { and, eq } from 'drizzle-orm';
import { TypeID, typeid } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, emails, folders, subscriptions, userProfiles } from '../drizzle';
import { EmailEvents, EmailFullSyncRequestedEvent } from './email/email.events';
import { FolderEvents, FolderSyncEvent } from './folder/folder.events';

@Injectable()
export class SyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly eventEmitter: EventEmitter2,
    @InjectTemporalClient() private readonly temporalClient: WorkflowClient,
  ) {}

  public async syncFolders(userProfileId: TypeID<'user_profile'>) {
    this.logger.log({ msg: 'Syncing folders', userProfileId });
    this.eventEmitter.emit(FolderEvents.FolderSync, new FolderSyncEvent(userProfileId));
  }

  public async syncFolderEmails(userProfileId: TypeID<'user_profile'>, folderId: string) {
    this.logger.log({ msg: 'Syncing folder emails', userProfileId, folderId });
    this.eventEmitter.emit(
      EmailEvents.EmailFullSyncRequested,
      new EmailFullSyncRequestedEvent(userProfileId, folderId),
    );
  }

  public async deleteAllUserData(userProfileId: TypeID<'user_profile'>) {
    this.logger.log({ msg: 'Wiping all user data', userProfileId });
    await Promise.all([
      this.db.delete(folders).where(eq(folders.userProfileId, userProfileId.toString())),
      this.db.delete(emails).where(eq(emails.userProfileId, userProfileId.toString())),
      this.db
        .delete(subscriptions)
        .where(eq(subscriptions.userProfileId, userProfileId.toString())),
      this.db
        .update(userProfiles)
        .set({ syncActivatedAt: null, syncDeactivatedAt: null, syncLastSyncedAt: null })
        .where(eq(userProfiles.id, userProfileId.toString())),
    ]);
  }

  public async reprocessEmail(userProfileId: TypeID<'user_profile'>, emailId: TypeID<'email'>) {
    this.logger.log({ msg: 'Reprocessing email', userProfileId, emailId });

    const email = await this.db.query.emails.findFirst({
      where: and(
        eq(emails.id, emailId.toString()),
        eq(emails.userProfileId, userProfileId.toString()),
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
