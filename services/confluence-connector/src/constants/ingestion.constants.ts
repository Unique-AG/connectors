export const IngestionMode = {
  Flat: 'flat',
} as const;

export type IngestionMode = (typeof IngestionMode)[keyof typeof IngestionMode];

export const CONFC_EXTERNAL_ID_PREFIX = 'confc:' as const;

export const IngestFiles = {
  Enabled: 'enabled',
  Disabled: 'disabled',
} as const;

export type IngestFiles = (typeof IngestFiles)[keyof typeof IngestFiles];

export const IngestionSourceKind = {
  Cloud: 'ATLASSIAN_CONFLUENCE_CLOUD',
  DataCenter: 'ATLASSIAN_CONFLUENCE_ONPREM',
} as const;

export type IngestionSourceKind = (typeof IngestionSourceKind)[keyof typeof IngestionSourceKind];

export function getSourceKind(instanceType: 'cloud' | 'data-center'): IngestionSourceKind {
  return instanceType === 'cloud' ? IngestionSourceKind.Cloud : IngestionSourceKind.DataCenter;
}

export const OWNER_TYPE = 'SCOPE' as const;
export const SOURCE_OWNER_TYPE = 'COMPANY' as const;

export const DEFAULT_MIME_TYPE = 'application/octet-stream' as const;

export const MIME_TYPES: Record<string, string> = {
  pdf: 'application/pdf',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  ppt: 'application/vnd.ms-powerpoint',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  txt: 'text/plain',
  csv: 'text/csv',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  svg: 'image/svg+xml',
  zip: 'application/zip',
  xml: 'application/xml',
  json: 'application/json',
  html: 'text/html',
  htm: 'text/html',
};
