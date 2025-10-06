import { AuthorizationCode, OAuthClient, OAuthSession } from '@unique-ag/mcp-oauth';
import { authorizationCodes, oauthClients, oauthSessions } from '../drizzle/schema';

export function toDrizzleOAuthClientInsert(client: OAuthClient): typeof oauthClients.$inferInsert {
  return {
    clientId: client.client_id,
    clientSecret: client.client_secret,
    clientName: client.client_name,
    clientDescription: client.client_description,
    logoUri: client.logo_uri,
    clientUri: client.client_uri,
    developerName: client.developer_name,
    developerEmail: client.developer_email,
    redirectUris: client.redirect_uris,
    grantTypes: client.grant_types,
    responseTypes: client.response_types,
    tokenEndpointAuthMethod: client.token_endpoint_auth_method,
    createdAt: client.created_at.toISOString(),
    updatedAt: client.updated_at.toISOString(),
  };
}

export function fromDrizzleOAuthClientRow(row: typeof oauthClients.$inferSelect): OAuthClient {
  return {
    client_id: row.clientId,
    client_secret: row.clientSecret ?? undefined,
    client_name: row.clientName,
    client_description: row.clientDescription ?? undefined,
    logo_uri: row.logoUri ?? undefined,
    client_uri: row.clientUri ?? undefined,
    developer_name: row.developerName ?? undefined,
    developer_email: row.developerEmail ?? undefined,
    redirect_uris: row.redirectUris,
    grant_types: row.grantTypes,
    response_types: row.responseTypes,
    token_endpoint_auth_method: row.tokenEndpointAuthMethod,
    created_at: new Date(row.createdAt),
    updated_at: new Date(row.updatedAt),
  };
}

export function toDrizzleAuthCodeInsert(
  code: AuthorizationCode,
): typeof authorizationCodes.$inferInsert {
  return {
    code: code.code,
    userId: code.user_id,
    clientId: code.client_id,
    redirectUri: code.redirect_uri,
    codeChallenge: code.code_challenge,
    codeChallengeMethod: code.code_challenge_method,
    resource: code.resource,
    scope: code.scope,
    expiresAt: new Date(code.expires_at),
    userProfileId: code.user_profile_id,
  };
}

export function fromDrizzleAuthCodeRow(
  row: typeof authorizationCodes.$inferSelect,
): AuthorizationCode {
  return {
    code: row.code,
    user_id: row.userId,
    client_id: row.clientId,
    redirect_uri: row.redirectUri,
    code_challenge: row.codeChallenge,
    code_challenge_method: row.codeChallengeMethod,
    resource: row.resource ?? undefined,
    scope: row.scope ?? undefined,
    expires_at: row.expiresAt.getTime(),
    user_profile_id: row.userProfileId,
  };
}

export function toDrizzleSessionInsert(session: OAuthSession): typeof oauthSessions.$inferInsert {
  return {
    sessionId: session.sessionId,
    state: session.state,
    clientId: session.clientId,
    redirectUri: session.redirectUri,
    codeChallenge: session.codeChallenge,
    codeChallengeMethod: session.codeChallengeMethod,
    oauthState: session.oauthState,
    scope: session.scope,
    resource: session.resource,
    expiresAt: new Date(session.expiresAt),
  };
}

export function fromDrizzleSessionRow(row: typeof oauthSessions.$inferSelect): OAuthSession {
  return {
    sessionId: row.sessionId,
    state: row.state,
    clientId: row.clientId ?? undefined,
    redirectUri: row.redirectUri ?? undefined,
    codeChallenge: row.codeChallenge ?? undefined,
    codeChallengeMethod: row.codeChallengeMethod ?? undefined,
    oauthState: row.oauthState ?? undefined,
    scope: row.scope ?? undefined,
    resource: row.resource ?? undefined,
    expiresAt: (row.expiresAt ?? new Date()).getTime(),
  };
}

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && Object.getPrototypeOf(v) === Object.prototype;

export function camelizeKeys(input: unknown): unknown {
  if (Array.isArray(input)) return input.map(camelizeKeys);
  if (isPlainObject(input)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(input)) {
      const ck = k.replace(/[_-]+([a-zA-Z0-9])/g, (_, c) => c.toUpperCase());
      // prefer explicit camelCase if both forms provided
      if (!(ck in out)) out[ck] = camelizeKeys(v);
    }
    return out;
  }
  return input;
}
