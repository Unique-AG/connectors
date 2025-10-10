import { TypeID } from 'typeid-js';

export enum FolderEvents {
  FolderSync = 'folder.sync',
}

export class FolderSyncEvent {
  public constructor(public readonly userProfileId: TypeID<'user_profile'>) {}
}
