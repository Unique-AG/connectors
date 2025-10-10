import { TypeID } from 'typeid-js';

export enum EmailEvents {
  EmailSyncStarted = 'email.sync.started',
  EmailSyncCompleted = 'email.sync.completed',
  EmailSyncFailed = 'email.sync.failed',
  EmailDeltaSyncRequested = 'email.delta.sync.requested',
}

export class EmailSyncStartedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly folderId: string,
    public readonly folderName: string,
    public readonly isInitialSync: boolean,
  ) {}
}

export class EmailSyncCompletedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly folderId: string,
    public readonly folderName: string,
    public readonly emailsProcessed: number,
    // public readonly emailsDeleted: number,
    public readonly deltaToken: string,
  ) {}
}

export class EmailSyncFailedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly folderId: string,
    public readonly folderName: string,
    public readonly error: Error,
  ) {}
}

export class EmailDeltaSyncRequestedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly folderId: string,
  ) {}
}
