import type { ListItemFields } from '../../types/sharepoint.types';
import type { IngestionApiResponse } from '../../unique-api/types/unique-api.types';

export interface ProcessingTokens {
  graphApiToken: string;
  uniqueApiToken: string;
  validatedAt: string;
}

export interface ProcessingMetadata {
  mimeType?: string;
  isFolder?: boolean;
  listItemFields?: ListItemFields;
  driveId?: string;
  siteId?: string;
  lastModifiedDateTime?: string;

  tokens?: ProcessingTokens;

  registration?: IngestionApiResponse;
  finalization?: { id: string };

  finalContentId?: string;
}


