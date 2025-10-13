import { TypeID } from 'typeid-js';

export enum EmailEvents {
  EmailFullSyncRequested = 'email.full.sync.requested',
  EmailDeltaSyncRequested = 'email.delta.sync.requested',
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
