import { describe, expect, it } from 'vitest';
import { CHAT_SCOPES, KB_SCOPES, resolveMicrosoftScopes, SCOPES } from './microsoft.provider';

describe(resolveMicrosoftScopes.name, () => {
  it('returns chat scopes only when Unique integration is disabled', () => {
    const scopes = resolveMicrosoftScopes('disabled');

    expect(scopes).toEqual(CHAT_SCOPES);
    for (const kbScope of KB_SCOPES) {
      expect(scopes).not.toContain(kbScope);
    }
  });

  it('returns chat and knowledge-base scopes when Unique integration is enabled', () => {
    expect(resolveMicrosoftScopes('enabled')).toEqual(SCOPES);
    expect(resolveMicrosoftScopes('enabled')).toEqual([...CHAT_SCOPES, ...KB_SCOPES]);
  });
});
