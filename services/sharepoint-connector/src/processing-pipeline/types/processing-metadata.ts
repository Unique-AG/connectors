import type { IngestionApiResponse } from '../../unique-api/unique-api.types';
import { FieldValueSet } from '@microsoft/microsoft-graph-types';

export interface ProcessingMetadata {
  mimeType?: string;
  isFolder?: boolean;
  listItemFields?: Record<string, FieldValueSet>;
  driveId?: string;
  siteId?: string;
  lastModifiedDateTime?: string;

  registration?: IngestionApiResponse;
  finalization?: { id: string };

  finalContentId?: string;
}
