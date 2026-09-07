import { describe, expect, it } from 'vitest';
import { type UserProfileSource, upgradedSource } from '../user-profiles.table';

describe(upgradedSource.name, () => {
  it.each([
    {
      case: 'no existing row',
      existing: undefined,
      listedAsSharedMailbox: true,
      expected: null,
    },
    {
      case: 'shared-mailbox gaining a token',
      existing: { source: 'shared-mailbox' as const, hasToken: true },
      listedAsSharedMailbox: true,
      expected: 'shared-mailbox-with-login',
    },
    {
      case: 'oauth with a token listed as a shared mailbox',
      existing: { source: 'oauth' as const, hasToken: true },
      listedAsSharedMailbox: true,
      expected: 'shared-mailbox-with-login',
    },
    {
      case: 'oauth with no token is never flipped',
      existing: { source: 'oauth' as const, hasToken: false },
      listedAsSharedMailbox: true,
      expected: null,
    },
    {
      case: 'already shared-mailbox-with-login is never downgraded',
      existing: { source: 'shared-mailbox-with-login' as const, hasToken: true },
      listedAsSharedMailbox: true,
      expected: null,
    },
  ] satisfies Array<{
    case: string;
    existing: { source: UserProfileSource; hasToken: boolean } | undefined;
    listedAsSharedMailbox: boolean;
    expected: UserProfileSource | null;
  }>)('$case', ({ existing, listedAsSharedMailbox, expected }) => {
    expect(upgradedSource(existing, listedAsSharedMailbox)).toBe(expected);
  });
});
