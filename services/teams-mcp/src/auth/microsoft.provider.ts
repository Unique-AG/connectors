import { type OAuthProviderConfig } from '@unique-ag/mcp-oauth';
import { Strategy as Microsoft } from 'passport-microsoft';

/** Always required for OAuth identity + chat/Teams messaging tools. */
export const CHAT_SCOPES = [
  'openid',
  'profile',
  'email',
  'offline_access',
  'User.Read', // (delegated): e1fe6dd8-ba31-4d61-89e7-88639da4683d
  'ChannelMessage.Send', // (delegated): send messages to channels
  'ChatMessage.Send', // (delegated): send messages to chats
  'Chat.ReadBasic', // (delegated): list user's chats
  'Chat.Read', // (delegated): read chat messages
  'Team.ReadBasic.All', // (delegated): list joined teams
  'Channel.ReadBasic.All', // (delegated): list channels in a team
  'ChannelMessage.Read.All', // (delegated): read channel messages
];

/**
 * Required only when UNIQUE_INTEGRATION=enabled for transcript/recording
 * knowledge-base ingestion.
 */
export const KB_SCOPES = [
  'Calendars.Read', // (delegated): 465a38f9-76ea-45b9-9f34-9e8b0d4b0b42
  'OnlineMeetings.Read', // (delegated): 9be106e1-f4e3-4df5-bdff-e4bc531cbe43
  'OnlineMeetingRecording.Read.All', // (delegated): 190c2bb6-1fdd-4fec-9aa2-7d571b5e1fe3
  'OnlineMeetingTranscript.Read.All', // (delegated): 30b87d18-ebb1-45db-97f8-82ccb1f0190c
];

/** Full scope set when Unique knowledge-base integration is enabled. */
export const SCOPES = [...CHAT_SCOPES, ...KB_SCOPES];

export function resolveMicrosoftScopes(uniqueIntegration: 'enabled' | 'disabled'): string[] {
  return uniqueIntegration === 'enabled' ? [...SCOPES] : [...CHAT_SCOPES];
}

export function createMicrosoftOAuthProvider(
  uniqueIntegration: 'enabled' | 'disabled',
): OAuthProviderConfig {
  const scopes = resolveMicrosoftScopes(uniqueIntegration);

  return {
    name: 'microsoft',
    strategy: Microsoft,
    strategyOptions: ({ serverUrl, clientId, clientSecret, callbackPath }) => ({
      clientID: clientId,
      clientSecret,
      callbackURL: serverUrl + callbackPath,
      scope: scopes,
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
