import type { ContentType } from '../confluence-api';

export interface DiscoveredPage {
  id: string;
  title: string;
  type: ContentType;
  spaceId: string;
  spaceKey: string;
  spaceName: string;
  versionTimestamp: string;
  webUrl: string;
  labels: string[];
}

export interface DiscoveredAttachment {
  id: string;
  title: string;
  mediaType: string;
  fileSize: number;
  downloadPath: string;
  versionTimestamp: string | undefined;
  pageId: string;
  spaceId: string;
  spaceKey: string;
  spaceName: string;
  webUrl: string;
}

export interface DiscoveryResult {
  pages: DiscoveredPage[];
  attachments: DiscoveredAttachment[];
}

export interface FileDiffResult {
  newItemIds: string[];
  updatedItemIds: string[];
  deletedItemIds: string[];
  movedItemIds: string[];
}

export interface FetchedPage {
  id: string;
  title: string;
  body: string;
  webUrl: string;
  spaceId: string;
  spaceKey: string;
  spaceName: string;
  metadata?: { confluenceLabels: string[] };
}
