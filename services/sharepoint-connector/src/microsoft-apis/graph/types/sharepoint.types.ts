import { ModerationStatusValue } from '../../../constants/moderation-status.constants';

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
  createdBy?: {
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
    CanvasContent1?: string; // This is the HTML content of the page for modern pages
    WikiField?: string; // This is the wiki content of the page for classic pages
    Title: string;
    FileSizeDisplay: string;
    FileLeafRef: string; // This is the file name of the page
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
  FileSizeDisplay: string;
  ItemChildCount: string;
  FolderChildCount: string;
  [key: string]: unknown;
}

// SimpleIdentitySet and SimplePermission types are built based on the response of the MS Graph API.
// We couldn't use the type from @microsoft/microsoft-graph-types because it seems to be incomplete.
// We need email of user the permission belongs to and while it is present in the response, it seems
// to be entirely omitted in the typings.
export interface SimpleIdentitySet {
  group?: {
    id: string;
    displayName: string;
  };
  siteGroup?: {
    id: string;
    displayName: string;
  };
  user?: {
    id: string;
    email: string;
  };
  siteUser?: {
    id: string;
    email: string;
    loginName: string;
  };
}

export interface SimplePermission {
  id: string;
  grantedToV2?: SimpleIdentitySet;
  grantedToIdentitiesV2?: SimpleIdentitySet[];
}

export interface GroupMember {
  '@odata.type': '#microsoft.graph.user' | '#microsoft.graph.group';
  id: string;
  displayName: string;
  mail: string | null;
  userPrincipalName?: string;
}
