import { FieldValueSet } from '@microsoft/microsoft-graph-types';
import type { IngestionApiResponse } from '../../unique-api/unique-api.types';

export interface ProcessingMetadata {
  mimeType: string | undefined;
  isFolder: boolean;
  listItemFields: Record<string, FieldValueSet>;
  driveId: string;
  siteId: string;
  driveName: string;
  folderPath: string;
  lastModifiedDateTime: string | undefined;

  registration?: IngestionApiResponse;
}
