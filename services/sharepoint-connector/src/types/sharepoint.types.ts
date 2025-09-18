export enum ModerationStatus {
  Approved = 0,
  Rejected = 1,
  Pending = 2,
  Draft = 3,
}
/*
export interface Drive {
  id: string;
  name: string;
  driveType: string;
  webUrl: string;
}

export interface DriveItem {
  id: string;
  name: string;
  webUrl: string;
  size?: number;
  lastModifiedDateTime?: string;
  folder?: {
    childCount: number;
  };
  file?: {
    mimeType: string;
  };
  listItem: ListItem;
  parentReference: ParentReference;
}

export interface ListItem {
  lastModifiedDateTime: string;
  createdDateTime: string;
  fields?: ListItemFields;
  parentReference?: ParentReference;
}

export interface ListItemFields {
  id: string;
  OData__ModerationStatus?: ModerationStatus;
  [key: string]: unknown;
}

export interface ParentReference {
  driveId: string;
  siteId: string;
  path?: string;
}

export interface SharePointApiResponseData<T> {
  '@odata.nextLink'?: string;
  value: T[];
}

*/
