import { describe, expect, it } from 'vitest';
import { resolveDirectoryIds } from '../resolve-directory-ids.util';

const dirs = [
  { providerDirectoryId: 'id-inbox', displayName: 'Inbox', internalType: 'Inbox' },
  { providerDirectoryId: 'id-sent', displayName: 'Sent Items', internalType: 'Sent Items' },
  { providerDirectoryId: 'id-custom', displayName: 'My Custom Folder', internalType: 'User Defined Directory' },
];

describe('resolveDirectoryIds', () => {
  it('exact provider ID match → resolvedIds includes it', () => {
    const { resolvedIds, unrecognized } = resolveDirectoryIds(['id-inbox'], dirs);
    expect(resolvedIds).toContain('id-inbox');
    expect(unrecognized).toHaveLength(0);
  });

  it('display name fuzzy match → resolvedIds includes the matching providerDirectoryId', () => {
    const { resolvedIds, unrecognized } = resolveDirectoryIds(['Inbox'], dirs);
    expect(resolvedIds).toContain('id-inbox');
    expect(unrecognized).toHaveLength(0);
  });

  it('unrecognized name → goes into unrecognized array', () => {
    const { resolvedIds, unrecognized } = resolveDirectoryIds(['CompletelyUnknownFolder'], dirs);
    expect(resolvedIds).toHaveLength(0);
    expect(unrecognized).toContain('CompletelyUnknownFolder');
  });

  it('empty string → silently ignored', () => {
    const { resolvedIds, unrecognized } = resolveDirectoryIds([''], dirs);
    expect(resolvedIds).toHaveLength(0);
    expect(unrecognized).toHaveLength(0);
  });

  it('mix: one recognized + one unrecognized → both parts correct', () => {
    const { resolvedIds, unrecognized } = resolveDirectoryIds(['Inbox', 'CompletelyUnknownFolder'], dirs);
    expect(resolvedIds).toContain('id-inbox');
    expect(unrecognized).toContain('CompletelyUnknownFolder');
  });

  it('system directory is preferred over user-defined when display names are equally similar', () => {
    // Both have a displayName very close to "My Folder".
    // The system one should win due to isNewItemBetter tie-breaking.
    // Note: the ordering here is intentional — user-id is first so that findBestMatch starts
    // with user-id as the best candidate. When system-id is evaluated with equal similarity,
    // isNewItemBetter(system-id, user-id) returns true (system directory beats user-defined),
    // so system-id takes over as the winner.
    // Both orderings actually produce the same result: if system-id were first, user-id would
    // fail isNewItemBetter(user-id, system-id) and system-id would stay as winner.
    const dirsWithTie = [
      { providerDirectoryId: 'user-id', displayName: 'My Folder', internalType: 'User Defined Directory' },
      { providerDirectoryId: 'system-id', displayName: 'My Folder', internalType: 'Inbox' },
    ];
    const { resolvedIds } = resolveDirectoryIds(['My Folder'], dirsWithTie);
    expect(resolvedIds).toContain('system-id');
    expect(resolvedIds).not.toContain('user-id');
  });
});
