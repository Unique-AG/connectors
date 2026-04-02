const EXTERNAL_ID_PREFIX = 'confc:' as const;

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

export function buildPartialKey(
  tenantName: string,
  spaceId: string,
  spaceKey: string,
  useV1KeyFormat: boolean,
): string {
  const base = `${spaceId}_${spaceKey}`;
  return useV1KeyFormat ? base : `${tenantName}/${base}`;
}
