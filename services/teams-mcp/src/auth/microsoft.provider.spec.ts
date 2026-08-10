import { describe, expect, it } from 'vitest';
import {
  CHAT_SCOPES,
  IDENTITY_SCOPES,
  KB_SCOPES,
  MESSAGING_SCOPES,
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
