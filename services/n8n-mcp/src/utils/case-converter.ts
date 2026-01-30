import { AuthorizationCode, OAuthClient, OAuthSession } from '@unique-ag/mcp-oauth';
import {
  AuthorizationCode as PrismaAuthorizationCode,
  OAuthClient as PrismaOAuthClient,
  OAuthSession as PrismaOAuthSession,
} from '@generated/prisma';

export function convertOAuthClientToPrisma(client: OAuthClient) {
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
    createdAt: client.created_at,
    updatedAt: client.updated_at,
  };
}

export function convertPrismaToOAuthClient(prismaClient: PrismaOAuthClient) {
  return {
    client_id: prismaClient.clientId,
    client_secret: prismaClient.clientSecret ?? undefined,
    client_name: prismaClient.clientName,
    client_description: prismaClient.clientDescription ?? undefined,
    logo_uri: prismaClient.logoUri ?? undefined,
    client_uri: prismaClient.clientUri ?? undefined,
    developer_name: prismaClient.developerName ?? undefined,
    developer_email: prismaClient.developerEmail ?? undefined,
    redirect_uris: prismaClient.redirectUris,
    grant_types: prismaClient.grantTypes,
    response_types: prismaClient.responseTypes,
    token_endpoint_auth_method: prismaClient.tokenEndpointAuthMethod,
    created_at: prismaClient.createdAt,
    updated_at: prismaClient.updatedAt,
  };
}

export function convertAuthCodeToPrisma(code: AuthorizationCode) {
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

export function convertPrismaToAuthCode(prismaCode: PrismaAuthorizationCode) {
  return {
    code: prismaCode.code,
    user_id: prismaCode.userId,
    client_id: prismaCode.clientId,
    redirect_uri: prismaCode.redirectUri,
    code_challenge: prismaCode.codeChallenge,
    code_challenge_method: prismaCode.codeChallengeMethod,
    resource: prismaCode.resource ?? undefined,
    scope: prismaCode.scope ?? undefined,
    expires_at: prismaCode.expiresAt.getTime(),
    user_profile_id: prismaCode.userProfileId,
  };
}

export function convertSessionToPrisma(session: OAuthSession) {
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

export function convertPrismaToSession(prismaSession: PrismaOAuthSession) {
  return {
    sessionId: prismaSession.sessionId,
    state: prismaSession.state,
    clientId: prismaSession.clientId ?? undefined,
    redirectUri: prismaSession.redirectUri ?? undefined,
    codeChallenge: prismaSession.codeChallenge ?? undefined,
    codeChallengeMethod: prismaSession.codeChallengeMethod ?? undefined,
    oauthState: prismaSession.oauthState ?? undefined,
    scope: prismaSession.scope ?? undefined,
    resource: prismaSession.resource ?? undefined,
    expiresAt: prismaSession.expiresAt.getTime(),
  };
}
