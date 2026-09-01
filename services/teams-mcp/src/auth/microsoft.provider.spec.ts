import { describe, expect, it } from 'vitest';
import {
  CHAT_SCOPES,
  createMicrosoftOAuthProvider,
  IDENTITY_SCOPES,
  KB_SCOPES,
  MESSAGING_SCOPES,
  microsoftOAuthTokenUrl,
  resolveMicrosoftScopes,
  SCOPES,
} from './microsoft.provider';

describe(resolveMicrosoftScopes.name, () => {
  it('full mode (chat + ingestion) requests identity, messaging and KB scopes', () => {
    const scopes = resolveMicrosoftScopes({ chat: 'enabled', ingestion: 'enabled' });

    expect(scopes).toEqual(SCOPES);
    expect(scopes).toEqual([...CHAT_SCOPES, ...KB_SCOPES]);
    expect(scopes).toEqual([...IDENTITY_SCOPES, ...MESSAGING_SCOPES, ...KB_SCOPES]);
  });

  it('chat-only mode (chat, no ingestion) requests identity and messaging but no KB scopes', () => {
    const scopes = resolveMicrosoftScopes({ chat: 'enabled', ingestion: 'disabled' });

    expect(scopes).toEqual(CHAT_SCOPES);
    expect(scopes).toEqual([...IDENTITY_SCOPES, ...MESSAGING_SCOPES]);
    for (const kbScope of KB_SCOPES) {
      expect(scopes).not.toContain(kbScope);
    }
  });

  it('ingestion-only mode (ingestion, no chat) requests identity and KB but no messaging scopes', () => {
    const scopes = resolveMicrosoftScopes({ chat: 'disabled', ingestion: 'enabled' });

    expect(scopes).toEqual([...IDENTITY_SCOPES, ...KB_SCOPES]);
    for (const messagingScope of MESSAGING_SCOPES) {
      expect(scopes).not.toContain(messagingScope);
    }
    for (const kbScope of KB_SCOPES) {
      expect(scopes).toContain(kbScope);
    }
    for (const identityScope of IDENTITY_SCOPES) {
      expect(scopes).toContain(identityScope);
    }
  });

  it('both disabled requests only identity scopes', () => {
    const scopes = resolveMicrosoftScopes({ chat: 'disabled', ingestion: 'disabled' });

    expect(scopes).toEqual(IDENTITY_SCOPES);
    for (const messagingScope of MESSAGING_SCOPES) {
      expect(scopes).not.toContain(messagingScope);
    }
    for (const kbScope of KB_SCOPES) {
      expect(scopes).not.toContain(kbScope);
    }
  });
});

describe(createMicrosoftOAuthProvider.name, () => {
  const strategyArgs = {
    serverUrl: 'https://teams.mcp.example.com',
    clientId: 'client-id',
    clientSecret: 'client-secret',
    callbackPath: '/auth/callback',
  };

  it('passes tenant common in strategy options', () => {
    const provider = createMicrosoftOAuthProvider({
      chat: 'enabled',
      ingestion: 'disabled',
      signInTenant: 'common',
    });

    expect(provider.strategyOptions(strategyArgs).tenant).toBe('common');
  });

  it('passes a pinned sign-in tenant in strategy options', () => {
    const signInTenant = 'f66cc3e7-9a7f-42ae-a0fa-adb72979b371';
    const provider = createMicrosoftOAuthProvider({
      chat: 'disabled',
      ingestion: 'enabled',
      signInTenant,
    });

    expect(provider.strategyOptions(strategyArgs).tenant).toBe(signInTenant);
  });
});

describe(microsoftOAuthTokenUrl.name, () => {
  it('builds the v2 token URL for the given tenant', () => {
    expect(microsoftOAuthTokenUrl('common')).toBe(
      'https://login.microsoftonline.com/common/oauth2/v2.0/token',
    );
    expect(microsoftOAuthTokenUrl('f66cc3e7-9a7f-42ae-a0fa-adb72979b371')).toBe(
      'https://login.microsoftonline.com/f66cc3e7-9a7f-42ae-a0fa-adb72979b371/oauth2/v2.0/token',
    );
  });
});
