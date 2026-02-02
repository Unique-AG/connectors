import { TypeID } from 'typeid-js';

export enum EmailEvents {
  EmailFullSyncRequested = 'email.full.sync.requested',
  EmailDeltaSyncRequested = 'email.delta.sync.requested',
  EmailSaved = 'email.saved',
  EmailDeleted = 'email.deleted',
}
export class EmailFullSyncRequestedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly folderId: string,
  ) {}
}

export class EmailDeltaSyncRequestedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly folderId: string,
  ) {}
}

export class EmailSavedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
  ) {}
}

export class EmailDeletedEvent {
  public constructor(
    public readonly userProfileId: TypeID<'user_profile'>,
    public readonly emailId: TypeID<'email'>,
  ) {}
}
