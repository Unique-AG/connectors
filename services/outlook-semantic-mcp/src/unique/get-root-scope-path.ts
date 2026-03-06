export const getRootScopePath = () => `/__Outlook MCP`;

export const getRootScopeExternalId = () => `/__Outlook MCP`;

export const getRootScopePathForUser = (userProviderIdentifier: string): string =>
  `${getRootScopePath()}/${userProviderIdentifier}_uncategoried`;

export const getRootScopeExternalIdForUser = (userProviderIdentifier: string): string =>
  `Outlook_${userProviderIdentifier}_uncategoried`;
