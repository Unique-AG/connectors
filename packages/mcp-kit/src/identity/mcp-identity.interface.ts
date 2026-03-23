export interface McpIdentity {
  userId: string;
  profileId: string;
  clientId: string;
  email: string | undefined;
  displayName: string | undefined;
  scopes: string[];
  resource: string;
  raw: unknown;
}
