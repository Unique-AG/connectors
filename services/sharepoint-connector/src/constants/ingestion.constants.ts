export const IngestionMode = {
  Flat: 'flat',
  Recursive: 'recursive',
} as const;

export type IngestionMode = (typeof IngestionMode)[keyof typeof IngestionMode];

export const INGESTION_SOURCE_NAME = 'Sharepoint' as const;
export const INGESTION_SOURCE_KIND = 'MICROSOFT_365_SHAREPOINT' as const;
export const PATH_BASED_INGESTION = 'PATH' as const;
