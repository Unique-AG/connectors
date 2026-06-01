import { describe, expect, it, vi } from 'vitest';
import type { DirectoryType } from '~/db';
import type {
  UserDirectory,
  UserMailbox,
} from '~/features/delegated-access/queries/list-mailboxes-and-directories.query';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { BuildMsGraphKqlBatchRequestsQuery } from '../build-ms-graph-kql-batch-requests.query';

const testUserId = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'own@example.com';
const OWN_PROFILE_ID = 'own-profile-id';
const DELEGATED_EMAIL = 'delegated@example.com';

function makeFolder(overrides: Partial<UserDirectory> & { id: string }): UserDirectory {
  return {
    displayName: `Folder ${overrides.id}`,
    internalType: 'User Defined Directory' as DirectoryType,
    canReadContent: true,
    children: [],
    ...overrides,
  };
}

function makeMailbox(overrides: Partial<UserMailbox> & { email: string }): UserMailbox {
  return {
    id: `user-${overrides.email}`,
    displayName: null,
    isOwn: false,
    hasFullAccess: false,
    folders: [],
    ...overrides,
  };
}

function createInstance(mailboxes: UserMailbox[]): BuildMsGraphKqlBatchRequestsQuery {
  const getUserProfileQuery = {
    run: vi.fn().mockResolvedValue({ id: OWN_PROFILE_ID, email: OWN_EMAIL }),
  };
  const listMailboxesAndDirectoriesQuery = {
    run: vi.fn().mockResolvedValue(mailboxes),
  };
  return new BuildMsGraphKqlBatchRequestsQuery(
    // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
    listMailboxesAndDirectoriesQuery as any,
    // biome-ignore lint/suspicious/noExplicitAny: constructor injection mocking
    getUserProfileQuery as any,
  );
}

describe('BuildMsGraphKqlBatchRequestsQuery', () => {
  describe('Case 1: own mailbox, no directories', () => {
    it('produces a single /messages request with isDelegated:false', async () => {
      const instance = createInstance([
        makeMailbox({ email: OWN_EMAIL, id: OWN_PROFILE_ID, isOwn: true, hasFullAccess: true }),
      ]);

      const { requests, skippedFolders } = await instance.run(testUserId, [
        { kqlQuery: 'subject:test' },
      ]);

      expect(requests).toHaveLength(1);
      expect(requests[0]?.folderId).toBeUndefined();
      expect(requests[0]?.isDelegated).toBe(false);
      expect(requests[0]?.mailbox).toBe(OWN_EMAIL);
      expect(skippedFolders).toHaveLength(0);
    });
  });

  describe('Case 2: full delegated mailbox, no directories', () => {
    it('produces a single /messages request with isDelegated:true', async () => {
      const instance = createInstance([
        makeMailbox({ email: OWN_EMAIL, id: OWN_PROFILE_ID, isOwn: true, hasFullAccess: true }),
        makeMailbox({ email: DELEGATED_EMAIL, isOwn: false, hasFullAccess: true }),
      ]);

      const { requests } = await instance.run(testUserId, [
        { kqlQuery: 'subject:test', mailbox: DELEGATED_EMAIL },
      ]);

      expect(requests).toHaveLength(1);
      expect(requests[0]?.folderId).toBeUndefined();
      expect(requests[0]?.isDelegated).toBe(true);
      expect(requests[0]?.mailbox).toBe(DELEGATED_EMAIL);
    });
  });

  describe('Case 3: directory-only delegated mailbox, no directories', () => {
    it('produces one request per canReadContent:true folder with isDelegated:true', async () => {
      const readableFolder = makeFolder({ id: 'folder-readable', canReadContent: true });
      const unreadableAncestor = makeFolder({ id: 'folder-ancestor', canReadContent: false });
      const instance = createInstance([
        makeMailbox({ email: OWN_EMAIL, id: OWN_PROFILE_ID, isOwn: true, hasFullAccess: true }),
        makeMailbox({
          email: DELEGATED_EMAIL,
          isOwn: false,
          hasFullAccess: false,
          folders: [unreadableAncestor, readableFolder],
        }),
      ]);

      const { requests } = await instance.run(testUserId, [
        { kqlQuery: 'subject:test', mailbox: DELEGATED_EMAIL },
      ]);

      expect(requests).toHaveLength(1);
      expect(requests[0]?.folderId).toBe('folder-readable');
      expect(requests[0]?.isDelegated).toBe(true);
    });

    it('skips non-readable ancestor directories and does not generate requests for them', async () => {
      const ancestor = makeFolder({ id: 'ancestor-id', canReadContent: false });
      const child1 = makeFolder({ id: 'child-1', canReadContent: true });
      const child2 = makeFolder({ id: 'child-2', canReadContent: true });
      const instance = createInstance([
        makeMailbox({
          email: DELEGATED_EMAIL,
          isOwn: false,
          hasFullAccess: false,
          folders: [ancestor, child1, child2],
        }),
      ]);

      const { requests } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: DELEGATED_EMAIL },
      ]);

      const folderIds = requests.map((r) => r.folderId);
      expect(folderIds).toContain('child-1');
      expect(folderIds).toContain('child-2');
      expect(folderIds).not.toContain('ancestor-id');
    });
  });

  describe('Case 4: directories specified', () => {
    it('resolves folder display name to provider ID and creates a per-folder request', async () => {
      const inbox = makeFolder({
        id: 'inbox-provider-id',
        displayName: 'Inbox',
        internalType: 'Inbox' as DirectoryType,
        canReadContent: true,
      });
      const instance = createInstance([
        makeMailbox({
          email: OWN_EMAIL,
          id: OWN_PROFILE_ID,
          isOwn: true,
          hasFullAccess: true,
          folders: [inbox],
        }),
      ]);

      const { requests, skippedFolders } = await instance.run(testUserId, [
        { kqlQuery: 'subject:test', directories: ['Inbox'] },
      ]);

      expect(requests).toHaveLength(1);
      expect(requests[0]?.folderId).toBe('inbox-provider-id');
      expect(requests[0]?.isDelegated).toBe(false);
      expect(skippedFolders).toHaveLength(0);
    });

    it('resolves exact provider ID match without fuzzy matching', async () => {
      const folder = makeFolder({ id: 'exact-provider-id', canReadContent: true });
      const instance = createInstance([
        makeMailbox({
          email: OWN_EMAIL,
          id: OWN_PROFILE_ID,
          isOwn: true,
          hasFullAccess: true,
          folders: [folder],
        }),
      ]);

      const { requests } = await instance.run(testUserId, [
        { kqlQuery: 'test', directories: ['exact-provider-id'] },
      ]);

      expect(requests).toHaveLength(1);
      expect(requests[0]?.folderId).toBe('exact-provider-id');
    });

    it('adds unresolvable folder name to skippedFolders and produces no request for it', async () => {
      const instance = createInstance([
        makeMailbox({
          email: OWN_EMAIL,
          id: OWN_PROFILE_ID,
          isOwn: true,
          hasFullAccess: true,
        }),
      ]);

      const { requests, skippedFolders } = await instance.run(testUserId, [
        { kqlQuery: 'test', directories: ['NonExistentFolder'] },
      ]);

      expect(requests).toHaveLength(0);
      expect(skippedFolders).toHaveLength(1);
      expect(skippedFolders[0]?.folder).toBe('NonExistentFolder');
      expect(skippedFolders[0]?.mailbox).toBe(OWN_EMAIL);
    });
  });

  describe('mailbox fan-out', () => {
    it('fans out to all accessible mailboxes when no mailbox filter is given', async () => {
      const instance = createInstance([
        makeMailbox({ email: OWN_EMAIL, id: OWN_PROFILE_ID, isOwn: true, hasFullAccess: true }),
        makeMailbox({ email: DELEGATED_EMAIL, isOwn: false, hasFullAccess: true }),
      ]);

      const { requests } = await instance.run(testUserId, [{ kqlQuery: 'test' }]);

      expect(requests).toHaveLength(2);
      expect(requests.map((r) => r.mailbox).sort()).toEqual([OWN_EMAIL, DELEGATED_EMAIL].sort());
    });

    it('returns no requests when specified mailbox is not in the accessible set', async () => {
      const instance = createInstance([
        makeMailbox({ email: OWN_EMAIL, id: OWN_PROFILE_ID, isOwn: true, hasFullAccess: true }),
      ]);

      const { requests } = await instance.run(testUserId, [
        { kqlQuery: 'test', mailbox: 'unknown@example.com' },
      ]);

      expect(requests).toHaveLength(0);
    });
  });
});
