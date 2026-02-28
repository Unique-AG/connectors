export const IngestionMode = {
  Flat: 'flat',
} as const;

export type IngestionMode = (typeof IngestionMode)[keyof typeof IngestionMode];

export const CONFC_EXTERNAL_ID_PREFIX = 'confc:' as const;

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
