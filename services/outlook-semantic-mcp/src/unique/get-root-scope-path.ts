export const getRootScopePath = () => `/Outlook MCP`;

export const getRootScopeExternalId = () => `/Outlook MCP`;

export const getRootScopePathForUser = (userProviderIdentifier: string): string =>
  `${getRootScopePath()}/${userProviderIdentifier}_uncategoried`;

export const getRootScopeExternalIdForUser = (userProviderIdentifier: string): string =>
  `OutlookMCP_${userProviderIdentifier}_uncategoried`;
