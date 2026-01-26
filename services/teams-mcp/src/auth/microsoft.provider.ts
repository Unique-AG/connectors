import { type OAuthProviderConfig } from '@unique-ag/mcp-oauth';
import { Strategy as Microsoft } from 'passport-microsoft';

export const SCOPES = [
  'openid',
  'profile',
  'email',
  'offline_access',
  'User.Read', // (delegated): e1fe6dd8-ba31-4d61-89e7-88639da4683d
  'Calendars.Read', // (delegated): 465a38f9-76ea-45b9-9f34-9e8b0d4b0b42
  'OnlineMeetings.Read', // (delegated): 9be106e1-f4e3-4df5-bdff-e4bc531cbe43
  'OnlineMeetingTranscript.Read.All', // (delegated): 30b87d18-ebb1-45db-97f8-82ccb1f0190c
];

export const MicrosoftOAuthProvider: OAuthProviderConfig = {
  name: 'microsoft',
  strategy: Microsoft,
  strategyOptions: ({ serverUrl, clientId, clientSecret, callbackPath }) => ({
    clientID: clientId,
    clientSecret,
    callbackURL: serverUrl + callbackPath,
    scope: SCOPES,
  }),
  profileMapper: (profile) => ({
    id: profile.id,
    username: profile.userPrincipalName,
    email: profile.emails?.[0]?.value,
    displayName: profile.displayName,
    raw: profile,
  }),
};
