export const IngestionMode = {
  Flat: 'flat',
} as const;

export const EnabledDisabledMode = {
  Enabled: 'enabled',
  Disabled: 'disabled',
} as const;

export type EnabledDisabledMode = (typeof EnabledDisabledMode)[keyof typeof EnabledDisabledMode];

export type IngestionMode = (typeof IngestionMode)[keyof typeof IngestionMode];

export const EXTERNAL_ID_PREFIX = 'confc:' as const;

export const IngestionSourceKind = {
  Cloud: 'ATLASSIAN_CONFLUENCE_CLOUD',
  DataCenter: 'ATLASSIAN_CONFLUENCE_ONPREM',
} as const;

export type IngestionSourceKind = (typeof IngestionSourceKind)[keyof typeof IngestionSourceKind];

export function getSourceKind(instanceType: 'cloud' | 'data-center'): IngestionSourceKind {
  return instanceType === 'cloud' ? IngestionSourceKind.Cloud : IngestionSourceKind.DataCenter;
}

export const INGESTION_MIME_TYPE = 'text/html' as const;
export const OWNER_TYPE = 'SCOPE' as const;
export const SOURCE_OWNER_TYPE = 'COMPANY' as const;
