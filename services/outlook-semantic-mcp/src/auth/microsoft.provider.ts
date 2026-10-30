import assert from 'node:assert';
import type * as http from 'node:http';
import { type OAuthProviderConfig } from '@unique-ag/mcp-oauth';
import { Strategy as MicrosoftStrategy } from 'passport-microsoft';
import { isCalendarEnabled } from '~/utils/backend-config.utils';

export const MAIL_SCOPES = [
  'openid',
  'profile',
  'email',
  'offline_access',
  'User.Read',
  'User.Read.All',
  'MailboxSettings.Read',
  'Mail.ReadWrite',
  'Mail.ReadWrite.Shared',
  'People.Read',
] as const;

export const CALENDAR_SCOPES = ['Calendars.ReadWrite.Shared'] as const;

export function getScopes(): string[] {
  return isCalendarEnabled() ? [...MAIL_SCOPES, ...CALENDAR_SCOPES] : [...MAIL_SCOPES];
}

export function microsoftOAuthTokenUrl(signInTenantId: string): string {
  return `https://login.microsoftonline.com/${signInTenantId}/oauth2/v2.0/token`;
}

function extractTid(accessToken: string): string {
  const parts = accessToken.split('.');
  assert.strictEqual(parts.length, 3, 'Access token is not a JWT');
  const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf-8')) as Record<
    string,
    unknown
  >;
  const tid = payload['tid'];
  assert.ok(typeof tid === 'string' && tid.length > 0, 'Access token has no tid claim');
  return tid;
}

interface OAuth2WithSetAgent {
  setAgent: (agent: http.Agent) => void;
}

export function createMicrosoftOAuthProvider(
  agent?: http.Agent,
  signInTenantId = 'common',
  allowedTenantIds: string[] = [],
): OAuthProviderConfig {
  class MicrosoftStrategyWithProxy extends MicrosoftStrategy {
    public constructor(...args: ConstructorParameters<typeof MicrosoftStrategy>) {
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
      scope: getScopes(),
      tenant: signInTenantId,
    }),
    profileMapper: (profile) => ({
      id: profile.id,
      username: profile.userPrincipalName,
      email: profile.emails?.[0]?.value,
      displayName: profile.displayName,
      raw: profile,
    }),
    validateCallback:
      allowedTenantIds.length > 0
        ? (accessToken: string) => {
            const tid = extractTid(accessToken);
            if (!allowedTenantIds.includes(tid)) {
              throw new Error(
                `Sign-in rejected: Entra tenant ${tid} is not on the allowlist`,
              );
            }
          }
        : undefined,
  };
}
