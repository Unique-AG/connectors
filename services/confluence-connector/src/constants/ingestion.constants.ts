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

export interface ParsedExternalId {
  tenantName: string;
  spaceId: string;
  spaceKey: string;
}

export function parseExternalId(externalId: string | undefined): ParsedExternalId | undefined {
  if (!externalId) {
    return undefined;
  }

  if (!externalId.startsWith(EXTERNAL_ID_PREFIX)) {
    return undefined;
  }

  const withoutPrefix = externalId.slice(EXTERNAL_ID_PREFIX.length);
  const segments = withoutPrefix.split(':');

  if (segments.length !== 3) {
    return undefined;
  }

  const [tenantName, spaceId, spaceKey] = segments as [string, string, string];
  return { tenantName, spaceId, spaceKey };
}

export function buildExternalId(tenantName: string, spaceId: string, spaceKey: string): string {
  return `${EXTERNAL_ID_PREFIX}${tenantName}:${spaceId}:${spaceKey}`;
}

export const INGESTION_MIME_TYPE = 'text/html' as const;
export const OWNER_TYPE = 'SCOPE' as const;
export const SOURCE_OWNER_TYPE = 'COMPANY' as const;
