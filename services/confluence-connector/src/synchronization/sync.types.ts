import type { Smeared } from '@unique-ag/utils';
import type { ContentType } from '../confluence-api';

export interface DiscoveredPage {
  id: string;
  title: Smeared;
  type: ContentType;
  spaceId: string;
  spaceKey: string;
  spaceName: string;
  versionTimestamp: string;
  webUrl: string;
  labels: string[];
}

export interface FileDiffResult {
  newPageIds: string[];
  updatedPageIds: string[];
  deletedPageIds: string[];
  movedPageIds: string[];
}

export interface FetchedPage {
  id: string;
  title: Smeared;
  body: string;
  webUrl: string;
  spaceId: string;
  spaceKey: string;
  spaceName: string;
  metadata?: { confluenceLabels: string[] };
}
