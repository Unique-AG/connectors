import { type OAuthProviderConfig } from '@unique-ag/mcp-oauth';
import { Strategy as Microsoft } from 'passport-microsoft';

export const SCOPES = [
  'openid',
  'profile',
  'email',
  'offline_access',
  'User.Read', // (delegated):
  'User.ReadBasic.All', // (delegated):
  'MailboxSettings.Read', // (delegated):
  'Mail.ReadWrite', // (delegated):
  'Mail.ReadWrite.Shared', // (delegated):
  'People.Read', // (delegated):
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
