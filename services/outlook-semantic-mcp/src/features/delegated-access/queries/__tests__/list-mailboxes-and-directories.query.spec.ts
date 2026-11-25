import { describe, expect, it, vi } from 'vitest';
import { loadFeaturesConfig } from '~/config';
import { ListMailboxesAndDirectoriesQuery } from '../list-mailboxes-and-directories.query';

const OWN_PROFILE = {
  id: 'user_profile_01h455vb4pex5vsknk084sn02q',
  email: 'ada@example.com',
  displayName: 'Ada',
};

const queryWith = (scan: string) => {
  const db = {
    query: {
      userProfiles: { findFirst: vi.fn().mockResolvedValue(OWN_PROFILE) },
      directories: { findMany: vi.fn().mockResolvedValue([]) },
    },
    execute: vi.fn().mockRejectedValue(new Error('delegated mailboxes were read')),
  };
  const features = loadFeaturesConfig({
    MCP_BACKEND: 'microsoft_graph',
    DELEGATED_ACCESS_SCAN: scan,
    MCP_TOOLS: JSON.stringify(['list_mailboxes_and_directories']),
  });
  return new ListMailboxesAndDirectoriesQuery(db as never, features);
};

describe(ListMailboxesAndDirectoriesQuery.name, () => {
  it('returns only the own mailbox with DELEGATED_ACCESS_SCAN=disabled, ignoring delegated rows', async () => {
    const mailboxes = await queryWith('disabled').run(OWN_PROFILE.id);

    expect(mailboxes).toEqual([
      {
        email: OWN_PROFILE.email,
        displayName: OWN_PROFILE.displayName,
        id: OWN_PROFILE.id,
        hasFullAccess: true,
        isOwn: true,
        folders: [],
      },
    ]);
  });

  it('reads the delegated mailboxes with shared mailboxes on', async () => {
    await expect(queryWith('full_access_only').run(OWN_PROFILE.id)).rejects.toThrow(
      'delegated mailboxes were read',
    );
  });
});
