import type * as http from 'node:http';
import { type OAuthProviderConfig } from '@unique-ag/mcp-oauth';
import { Strategy as MicrosoftStrategy } from 'passport-microsoft';

export const SCOPES = [
  'openid',
  'profile',
  'email',
  'offline_access',
  'User.Read', // (delegated):
  'User.Read.All', // (delegated):
  'MailboxSettings.Read', // (delegated):
  'Mail.ReadWrite', // (delegated):
  'Mail.ReadWrite.Shared', // (delegated):
  'People.Read', // (delegated):
];

type OAuth2WithSetAgent = {
  setAgent: (agent: http.Agent) => void;
};

export function createMicrosoftOAuthProvider(agent?: http.Agent): OAuthProviderConfig {
  class MicrosoftStrategyWithProxy extends MicrosoftStrategy {
    constructor(...args: ConstructorParameters<typeof MicrosoftStrategy>) {
      super(...args);
      if (agent) {
        // _oauth2 is assigned in passport-oauth2 constructor; setAgent covers token + profile
        (this as unknown as { _oauth2: OAuth2WithSetAgent })._oauth2.setAgent(agent);
      }
    }
  }

  return {
    name: 'microsoft',
    strategy: MicrosoftStrategyWithProxy,
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
}
