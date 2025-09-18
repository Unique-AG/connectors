import type { IngestionApiResponse } from '../../unique-api/types/unique-api.types';

export interface ProcessingMetadata {
  mimeType?: string;
  isFolder?: boolean;
  listItemFields?: Record<string, unknown>;
  driveId?: string;
  siteId?: string;
  lastModifiedDateTime?: string;

  registration?: IngestionApiResponse;
  finalization?: { id: string };

  finalContentId?: string;
}
