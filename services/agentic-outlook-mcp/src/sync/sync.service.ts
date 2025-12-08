import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { eq } from 'drizzle-orm';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase, emails, folders, subscriptions, userProfiles } from '../drizzle';
import { EmailEvents, EmailFullSyncRequestedEvent } from './email/email.events';
import { FolderEvents, FolderSyncEvent } from './folder/folder.events';

@Injectable()
export class SyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly eventEmitter: EventEmitter2,
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
}
