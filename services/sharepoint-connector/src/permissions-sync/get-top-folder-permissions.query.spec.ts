import { Logger } from '@nestjs/common';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { Smeared } from '../utils/smeared';
import { GetTopFolderPermissionsQuery } from './get-top-folder-permissions.query';
import type { GroupMembership, Membership } from './types';

describe('GetTopFolderPermissionsQuery', () => {
  let query: GetTopFolderPermissionsQuery;
  let loggerWarnSpy: ReturnType<typeof vi.fn>;

  const mockSiteId = 'site-123';
  const rootPath = new Smeared('TestSite', false);

  const createMockFile = (id: string, webUrl: string): SharepointContentItem => ({
    itemType: 'driveItem',
    siteId: new Smeared(mockSiteId, false),
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: '/test',
    fileName: 'test-file.docx',
    item: {
      '@odata.etag': 'etag-1',
      id,
      name: 'test-file.docx',
      webUrl,
      size: 1024,
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
      file: {
        mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        hashes: { quickXorHash: 'hash-1' },
      },
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
          FileLeafRef: 'test-file.docx',
          Modified: '2025-01-01T00:00:00Z',
          Created: '2025-01-01T00:00:00Z',
          ContentType: 'Document',
          AuthorLookupId: '1',
          EditorLookupId: '1',
          FileSizeDisplay: '1024',
          ItemChildCount: '0',
          FolderChildCount: '0',
        },
      },
    },
  });

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

  const createSiteGroupMembership = (id: string, name: string): GroupMembership => ({
    type: 'siteGroup',
    id,
    name,
  });

  const createUserMembership = (email: string): Membership => ({
    type: 'user',
    email,
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

    const { unit } = await TestBed.solitary(GetTopFolderPermissionsQuery).compile();
    query = unit;
  });

  it('aggregates groups from files under site scope', () => {
    const file = createMockFile(
      'file-1',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/file.docx',
    );
    const topFolder = createMockDirectory(
      'docs',
      'https://tenant.sharepoint.com/sites/TestSite/Documents',
    );
    const group = createSiteGroupMembership('group-1', 'Test Group');

    const permissionsMap = {
      [`${mockSiteId}/${file.item.id}`]: [group],
      [`${mockSiteId}/${topFolder.item.id}`]: [],
    };

    const result = query.run({
      items: [file],
      directories: [topFolder],
      permissionsMap,
      rootPath,
    });

    expect(result.get('/TestSite')).toEqual([group]);
  });

  it('aggregates groups from directories under site scope', () => {
    const topFolder = createMockDirectory(
      'docs',
      'https://tenant.sharepoint.com/sites/TestSite/Documents',
    );
    const subFolder = createMockDirectory(
      'subfolder',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/Sub',
    );
    const group = createSiteGroupMembership('group-dir', 'Directory Group');

    const permissionsMap = {
      [`${mockSiteId}/${topFolder.item.id}`]: [],
      [`${mockSiteId}/${subFolder.item.id}`]: [group],
    };

    const result = query.run({
      items: [],
      directories: [topFolder, subFolder],
      permissionsMap,
      rootPath,
    });

    expect(result.get('/TestSite')).toEqual([group]);
    expect(result.get('/TestSite/Documents')).toEqual([group]);
  });

  it('includes library folder when only subfolders exist', () => {
    const subFolder = createMockDirectory(
      'subfolder',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/Sub',
    );
    const group = createSiteGroupMembership('group-dir', 'Directory Group');

    const permissionsMap = {
      [`${mockSiteId}/${subFolder.item.id}`]: [group],
    };

    const result = query.run({
      items: [],
      directories: [subFolder],
      permissionsMap,
      rootPath,
    });

    expect(result.get('/TestSite/Documents')).toEqual([group]);
  });

  it('filters out user permissions and only includes groups', () => {
    const file = createMockFile(
      'file-1',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/file.docx',
    );
    const topFolder = createMockDirectory(
      'docs',
      'https://tenant.sharepoint.com/sites/TestSite/Documents',
    );
    const group = createSiteGroupMembership('group-1', 'Test Group');
    const user = createUserMembership('user@example.com');

    const permissionsMap = {
      [`${mockSiteId}/${file.item.id}`]: [group, user],
      [`${mockSiteId}/${topFolder.item.id}`]: [group, user],
    };

    const result = query.run({
      items: [file],
      directories: [topFolder],
      permissionsMap,
      rootPath,
    });

    const sitePermissions = result.get('/TestSite');
    expect(sitePermissions).toEqual([group]);
    // We need to type cast to string because in type system `user` is never returned, but we want
    // to be sure anyway.
    expect(sitePermissions?.some((p) => (p.type as string) === 'user')).toBe(false);
  });

  it('library scope only includes its descendants', () => {
    const docsFolder = createMockDirectory(
      'docs',
      'https://tenant.sharepoint.com/sites/TestSite/Documents',
    );
    const sharedFolder = createMockDirectory(
      'shared',
      'https://tenant.sharepoint.com/sites/TestSite/Shared',
    );
    const docsFile = createMockFile(
      'docs-file',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/doc.docx',
    );
    const sharedFile = createMockFile(
      'shared-file',
      'https://tenant.sharepoint.com/sites/TestSite/Shared/shared.docx',
    );

    const docsGroup = createSiteGroupMembership('docs-group', 'Docs Group');
    const sharedGroup = createSiteGroupMembership('shared-group', 'Shared Group');

    const permissionsMap = {
      [`${mockSiteId}/${docsFolder.item.id}`]: [],
      [`${mockSiteId}/${sharedFolder.item.id}`]: [],
      [`${mockSiteId}/${docsFile.item.id}`]: [docsGroup],
      [`${mockSiteId}/${sharedFile.item.id}`]: [sharedGroup],
    };

    const result = query.run({
      items: [docsFile, sharedFile],
      directories: [docsFolder, sharedFolder],
      permissionsMap,
      rootPath,
    });

    expect(result.get('/TestSite/Documents')).toEqual([docsGroup]);
    expect(result.get('/TestSite/Shared')).toEqual([sharedGroup]);
  });

  it('returns empty permissions for empty site', () => {
    const result = query.run({
      items: [],
      directories: [],
      permissionsMap: {},
      rootPath,
    });

    expect(result.get('/TestSite')).toEqual([]);
  });

  it('deduplicates groups from multiple items', () => {
    const file1 = createMockFile(
      'file-1',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/file1.docx',
    );
    const file2 = createMockFile(
      'file-2',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/file2.docx',
    );
    const topFolder = createMockDirectory(
      'docs',
      'https://tenant.sharepoint.com/sites/TestSite/Documents',
    );
    const sameGroup = createSiteGroupMembership('group-shared', 'Shared Group');

    const permissionsMap = {
      [`${mockSiteId}/${file1.item.id}`]: [sameGroup],
      [`${mockSiteId}/${file2.item.id}`]: [sameGroup],
      [`${mockSiteId}/${topFolder.item.id}`]: [],
    };

    const result = query.run({
      items: [file1, file2],
      directories: [topFolder],
      permissionsMap,
      rootPath,
    });

    const sitePermissions = result.get('/TestSite');
    const matchingGroups = sitePermissions?.filter(
      (p) => p.type === 'siteGroup' && p.id === 'group-shared',
    );
    expect(matchingGroups).toHaveLength(1);
  });

  it('handles missing permissions gracefully and logs warning', () => {
    const topFolder = createMockDirectory(
      'docs',
      'https://tenant.sharepoint.com/sites/TestSite/Documents',
    );
    const file = createMockFile(
      'orphan-file',
      'https://tenant.sharepoint.com/sites/TestSite/Documents/orphan.docx',
    );

    const permissionsMap = {
      [`${mockSiteId}/${topFolder.item.id}`]: [],
    };

    const result = query.run({
      items: [file],
      directories: [topFolder],
      permissionsMap,
      rootPath,
    });

    expect(result.get('/TestSite')).toEqual([]);
    expect(loggerWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining(
        `No SharePoint permissions found for item with key ${mockSiteId}/orphan-file`,
      ),
    );
  });
});
