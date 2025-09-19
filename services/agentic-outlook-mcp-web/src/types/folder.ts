export interface OutlookFolder {
  id: string;
  name: string;
  path: string;
  parentId?: string;
  children?: OutlookFolder[];
  syncEnabled: boolean;
  syncActivatedAt?: Date;
  syncDeactivatedAt?: Date;
  lastSyncAt?: Date;
  emailCount: number;
  totalEmailCount: number; // includes emails from child folders
}

export interface SyncStats {
  totalFolders: number;
  syncedFolders: number;
  totalEmails: number;
  lastGlobalSync?: Date;
  globalSyncEnabled: boolean;
}
