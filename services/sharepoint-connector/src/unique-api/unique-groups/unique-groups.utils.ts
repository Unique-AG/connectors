const SHAREPOINT_CONNECTOR_GROUP_EXTERNAL_ID_PREFIX = 'SPC-';

export function getSharepointConnectorGroupExternalId(siteId: string, groupId: string): string {
  return `${getSharepointConnectorGroupExternalIdPrefix(siteId)}${groupId}`;
}

export function getSharepointConnectorGroupExternalIdPrefix(siteId: string): string {
  return `${SHAREPOINT_CONNECTOR_GROUP_EXTERNAL_ID_PREFIX}${siteId}__`;
}
