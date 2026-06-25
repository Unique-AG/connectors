import { describe, expect, it, vi } from 'vitest';
import { BuildWebLinksCommand, webLinkMapKey } from '../build-web-links.command';

const OWN_EMAIL = 'user@example.com';
const SHARED_EMAIL = 'shared@example.com';
const USER_PROFILE_ID = 'user-1';

function makeCommand(translateResult: Map<string, string> = new Map()) {
  const translateQuery = { run: vi.fn().mockResolvedValue(translateResult) };
  return { command: new BuildWebLinksCommand(translateQuery as never), translateQuery };
}

describe('BuildWebLinksCommand', () => {
  it('returns own-mailbox webLink as-is without calling translation', async () => {
    const { command, translateQuery } = makeCommand();
    const result = await command.run({
      userProfileId: USER_PROFILE_ID,
      userProfileEmail: OWN_EMAIL,
      ids: [
        { id: 'msg-1', isImmutable: true, mailbox: OWN_EMAIL, webLink: 'https://outlook.test/own' },
      ],
    });

    expect(result.get(webLinkMapKey(OWN_EMAIL, 'msg-1'))).toBe('https://outlook.test/own');
    expect(translateQuery.run).not.toHaveBeenCalled();
  });

  it('builds OWA URL from translated RestId for delegated immutable IDs', async () => {
    const { command } = makeCommand(new Map([['immutable-1', 'rest-1']]));
    const result = await command.run({
      userProfileId: USER_PROFILE_ID,
      userProfileEmail: OWN_EMAIL,
      ids: [{ id: 'immutable-1', isImmutable: true, mailbox: SHARED_EMAIL, webLink: '' }],
    });

    expect(result.get(webLinkMapKey(SHARED_EMAIL, 'immutable-1'))).toBe(
      'https://outlook.office365.com/owa/?ItemID=rest-1&exvsurl=1&viewmodel=ReadMessageItem',
    );
  });

  it('builds OWA URL directly for delegated RestIds without calling translation', async () => {
    const { command, translateQuery } = makeCommand();
    const result = await command.run({
      userProfileId: USER_PROFILE_ID,
      userProfileEmail: OWN_EMAIL,
      ids: [{ id: 'rest-1', isImmutable: false, mailbox: SHARED_EMAIL, webLink: '' }],
    });

    expect(result.get(webLinkMapKey(SHARED_EMAIL, 'rest-1'))).toBe(
      'https://outlook.office365.com/owa/?ItemID=rest-1&exvsurl=1&viewmodel=ReadMessageItem',
    );
    expect(translateQuery.run).not.toHaveBeenCalled();
  });

  it('returns empty string when translation fails to resolve an immutable ID', async () => {
    const { command } = makeCommand(new Map());
    const result = await command.run({
      userProfileId: USER_PROFILE_ID,
      userProfileEmail: OWN_EMAIL,
      ids: [{ id: 'immutable-1', isImmutable: true, mailbox: SHARED_EMAIL, webLink: '' }],
    });

    expect(result.get(webLinkMapKey(SHARED_EMAIL, 'immutable-1'))).toBe('');
  });

  it('URL-encodes special characters in RestIds', async () => {
    const { command } = makeCommand(new Map([['immutable-1', 'rest+id/with=chars']]));
    const result = await command.run({
      userProfileId: USER_PROFILE_ID,
      userProfileEmail: OWN_EMAIL,
      ids: [{ id: 'immutable-1', isImmutable: true, mailbox: SHARED_EMAIL, webLink: '' }],
    });

    expect(result.get(webLinkMapKey(SHARED_EMAIL, 'immutable-1'))).toContain(
      'ItemID=rest%2Bid%2Fwith%3Dchars',
    );
  });
});
