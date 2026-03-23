/** Normalised identity of the authenticated caller for the current MCP request. */
export interface McpIdentity {
  /** Platform user identifier (falls back to token `sub` claim when no explicit `userId`). */
  userId: string;
  /** User profile identifier within the platform. */
  profileId: string;
  /** OAuth client ID that issued the token. */
  clientId: string;
  /** User's email address, if provided by the token. */
  email: string | undefined;
  /** Human-readable display name, if provided by the token. */
  displayName: string | undefined;
  /** Space-separated OAuth scopes granted to the token, split into an array. */
  scopes: string[];
  /** Target resource audience from the token (`resource` claim). */
  resource: string;
  /** Raw token validation result for cases where normalised fields are insufficient. */
  raw: unknown;
}
