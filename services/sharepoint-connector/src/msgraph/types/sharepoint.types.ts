import { ModerationStatusValue } from '../../constants/moderation-status.constants';

export interface GraphApiErrorResponse {
  statusCode?: number;
  code?: string;
  body?: unknown;
  requestId?: string;
  innerError?: unknown;
  response?: {
    status?: number;
    headers?: Headers | Record<string, string>;
  };
}

export function isGraphApiError(error: unknown): error is GraphApiErrorResponse {
  return (
    typeof error === 'object' &&
    error !== null &&
    ('statusCode' in error || 'code' in error || 'body' in error || 'requestId' in error)
  );
}

export interface GraphApiResponse<T> {
  '@odata.context'?: string;
  '@odata.nextLink'?: string;
  value: T[];
}

// Typing built from the response of the MS Graph API
export interface ListItemDetailsResponse {
  id: string;
  webUrl?: string;
  createdDateTime?: string;
  lastModifiedDateTime?: string;
  '@odata.context': string;
  '@odata.etag': string;
  parentReference?: {
    id: string;
    siteId: string;
  };
  contentType?: {
    id: string;
    name: string;
  };
  fields: {
    '@odata.etag': string;
    Title: string;
    WikiField?: string;
    CanvasContent1?: string;
  };
}

export interface SitePageContent {
  canvasContent?: string;
  wikiField?: string;
  title: string;
}

// Typing built from the response of the MS Graph API
export interface ListItem {
  id: string;
  lastModifiedDateTime: string;
  createdDateTime: string;
  webUrl: string;
  createdBy: {
    user: {
      email: string;
      id: string;
      displayName: string;
    };
  };
  fields: {
    '@odata.etag': string;
    FinanceGPTKnowledge: boolean;
    _ModerationStatus: ModerationStatusValue;
    CanvasContent1?: string;
    WikiField?: string;
    Title: string;
    FileSizeDisplay: string;
    FileLeafRef: string;
    [key: string]: unknown;
  };
}

// Typing built from the response of the MS Graph API
export interface DriveItem {
  '@odata.etag': string;
  id: string;
  name: string;
  webUrl: string;
  size: number;
  lastModifiedDateTime: string;
  parentReference: {
    driveType: string;
    driveId: string;
    id: string;
    name: string;
    path: string;
    siteId: string;
  };
  folder?: {
    childCount: number;
  };
  file?: {
    mimeType: string;
    hashes: {
      quickXorHash: string;
    };
  };

  /** When expanded using ?expand=listItem($expand=fields) */
  listItem: {
    '@odata.etag': string;
    id: string;
    eTag: string;
    createdDateTime: string;
    lastModifiedDateTime: string;
    webUrl: string;
    parentReference?: {
      id?: string;
      siteId?: string;
    };
    contentType?: {
      id?: string;
      name?: string;
    };
    fields: DriveItemFields;
  };
}

// Typing built from the response of the MS Graph API
export interface DriveItemFields {
  '@odata.etag': string;
  FinanceGPTKnowledge: boolean;
  FileLeafRef: string;
  Modified: string;
  Created: string;
  ContentType: string;
  AuthorLookupId: string;
  EditorLookupId: string;
  ItemChildCount: string;
  FolderChildCount: string;
  [key: string]: unknown;
}
