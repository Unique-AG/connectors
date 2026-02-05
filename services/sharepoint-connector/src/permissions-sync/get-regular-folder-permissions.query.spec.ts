import { Logger } from '@nestjs/common';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SharepointDirectoryItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { Smeared } from '../utils/smeared';
import { GetRegularFolderPermissionsQuery } from './get-regular-folder-permissions.query';
import type { Membership } from './types';

describe('GetRegularFolderPermissionsQuery', () => {
  let query: GetRegularFolderPermissionsQuery;
  let loggerWarnSpy: ReturnType<typeof vi.fn>;

  const mockSiteId = 'site-123';
  const rootPath = new Smeared('TestSite', false);

  const createMockDirectory = (id: string, webUrl: string): SharepointDirectoryItem => ({
    itemType: 'directory',
    siteId: new Smeared(mockSiteId, false),
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: '/test',
    fileName: '',
    item: {
      '@odata.etag': 'etag-1',
      id,
      name: 'test-folder',
      webUrl,
      size: 0,
      createdDateTime: '2025-01-01T00:00:00Z',
      lastModifiedDateTime: '2025-01-01T00:00:00Z',
      createdBy: { user: { id: 'user-1', email: 'test@example.com', displayName: 'Test' } },
      parentReference: {
        driveType: 'documentLibrary',
        driveId: 'drive-1',
        id: 'parent-id',
        name: 'Documents',
        path: '/drive/root:/test',
        siteId: mockSiteId,
      },
      folder: { childCount: 0 },
      listItem: {
        '@odata.etag': 'etag-2',
        id: `list-item-${id}`,
        eTag: 'etag-2',
        createdDateTime: '2025-01-01T00:00:00Z',
        lastModifiedDateTime: '2025-01-01T00:00:00Z',
        webUrl,
        createdBy: { user: { id: 'user-1', email: 'test@example.com', displayName: 'Test' } },
        fields: {
          '@odata.etag': 'etag-2',
          FileLeafRef: 'test-folder',
          Modified: '2025-01-01T00:00:00Z',
          Created: '2025-01-01T00:00:00Z',
          ContentType: 'Folder',
          AuthorLookupId: '1',
          EditorLookupId: '1',
          FileSizeDisplay: '0',
          ItemChildCount: '0',
          FolderChildCount: '0',
        },
      },
    },
  });

  const createGroupMembership = (id: string, name: string): Membership => ({
    type: 'siteGroup',
    id,
    name,
  });

  beforeEach(async () => {
    loggerWarnSpy = vi.fn();
    vi.mocked(Logger).mockImplementation(
      () =>
        ({
          log: vi.fn(),
          error: vi.fn(),
          warn: loggerWarnSpy,
          debug: vi.fn(),
          verbose: vi.fn(),
        }) as unknown as Logger,
    );

    const { unit } = await TestBed.solitary(GetRegularFolderPermissionsQuery).compile();
    query = unit;
  });

  it('returns directory permissions for level 2+ folders', () => {
    const directory = createMockDirectory(
      'folder-1',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/Folder1',
    );
    const permissionsKey = `${mockSiteId}/${directory.item.id}`;
    const permissions = [createGroupMembership('group-1', 'Test Group')];

    const result = query.run({
      directories: [directory],
      permissionsMap: { [permissionsKey]: permissions },
      rootPath,
    });

    expect(result.size).toBe(1);
    expect(result.get('/TestSite/Documents/Folder1')).toEqual(permissions);
  });

  it('skips top folders at site level', () => {
    const topFolder1 = createMockDirectory(
      'docs',
      'https://tenant.sharepoint.com/sites/TestSite/Documents',
    );
    const topFolder2 = createMockDirectory(
      'shared',
      'https://tenant.sharepoint.com/sites/TestSite/Shared',
    );

    const permissionsMap = {
      [`${mockSiteId}/${topFolder1.item.id}`]: [createGroupMembership('g1', 'Group 1')],
      [`${mockSiteId}/${topFolder2.item.id}`]: [createGroupMembership('g2', 'Group 2')],
    };

    const result = query.run({
      directories: [topFolder1, topFolder2],
      permissionsMap,
      rootPath,
    });

    expect(result.size).toBe(0);
  });

  it('skips top folders and includes regular folders in mixed input', () => {
    const topFolder = createMockDirectory(
      'top-folder',
      'https://tenant.sharepoint.com/sites/TestSite/Documents',
    );
    const regularFolder = createMockDirectory(
      'regular-folder',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/Subfolder',
    );

    const permissionsMap = {
      [`${mockSiteId}/${topFolder.item.id}`]: [createGroupMembership('group-top', 'Top Group')],
      [`${mockSiteId}/${regularFolder.item.id}`]: [
        createGroupMembership('group-regular', 'Regular Group'),
      ],
    };

    const result = query.run({
      directories: [topFolder, regularFolder],
      permissionsMap,
      rootPath,
    });

    expect(result.size).toBe(1);
    expect(result.has('/TestSite/Documents')).toBe(false);
    expect(result.get('/TestSite/Documents/Subfolder')).toEqual([
      createGroupMembership('group-regular', 'Regular Group'),
    ]);
  });

  it('handles missing permissions gracefully and logs warning', () => {
    const directory = createMockDirectory(
      'folder-no-perms',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/NoPermsFolder',
    );

    const result = query.run({
      directories: [directory],
      permissionsMap: {},
      rootPath,
    });

    expect(result.size).toBe(0);
    expect(loggerWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining(
        `No SharePoint permissions found for directory with key ${mockSiteId}/folder-no-perms`,
      ),
    );
  });
});
