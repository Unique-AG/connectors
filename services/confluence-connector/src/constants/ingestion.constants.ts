export const IngestionMode = {
  Flat: 'flat',
  Recursive: 'recursive',
} as const;

export type IngestionMode = (typeof IngestionMode)[keyof typeof IngestionMode];

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
