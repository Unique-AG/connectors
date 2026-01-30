import { OAuthProviderConfig } from '@unique-ag/mcp-oauth';
import { ZitadelOIDCStrategy, ZitadelProfile } from './zitadel-oidc.strategy';

export const createZitadelOAuthProvider = ({
  issuer,
  requiredRole,
}: {
  issuer: string;
  requiredRole?: string;
}): OAuthProviderConfig => ({
  name: 'zitadel',
  strategy: ZitadelOIDCStrategy,
  strategyOptions: ({ serverUrl, clientId, clientSecret, callbackPath }) => ({
    issuer,
    clientID: clientId,
    clientSecret,
    callbackURL: `${serverUrl}${callbackPath}`,
    scope: ['openid', 'profile', 'email'],
    requiredRole,
    passReqToCallback: false,
  }),
  profileMapper: (profile: ZitadelProfile) => ({
    id: profile.id,
    username: profile.username || profile.preferred_username || profile.id,
    email: profile.email,
    displayName: profile.displayName || profile.name || profile.preferred_username,
    raw: profile,
  }),
});
