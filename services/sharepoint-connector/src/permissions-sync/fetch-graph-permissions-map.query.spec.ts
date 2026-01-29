import { Logger } from '@nestjs/common';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import {
  SimpleIdentitySet,
  SimplePermission,
} from '../microsoft-apis/graph/types/sharepoint.types';
import type { AnySharepointItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { createSmeared } from '../utils/smeared';
import { FetchGraphPermissionsMapQuery } from './fetch-graph-permissions-map.query';

describe('FetchGraphPermissionsMapQuery', () => {
  let query: FetchGraphPermissionsMapQuery;
  let graphApiService: GraphApiService;
  let loggerWarnSpy: ReturnType<typeof vi.fn>;

  const mockSiteId = 'site-123';
  const mockSiteName = 'TestSite';

  const createMockDriveItem = (id: string): AnySharepointItem => ({
    itemType: 'driveItem',
    item: {
      '@odata.etag': 'etag-1',
      id,
      name: 'test-file.docx',
      webUrl: 'https://example.sharepoint.com/test',
      size: 1024,
      createdDateTime: '2025-01-01T00:00:00Z',
      lastModifiedDateTime: '2025-01-01T00:00:00Z',
      createdBy: {
        user: {
          email: 'test@example.com',
          id: 'user-1',
          displayName: 'Test User',
        },
      },
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
        hashes: {
          quickXorHash: 'hash-1',
        },
      },
      listItem: {
        '@odata.etag': 'etag-2',
        id: `list-item-${id}`,
        eTag: 'etag-2',
        createdDateTime: '2025-01-01T00:00:00Z',
        lastModifiedDateTime: '2025-01-01T00:00:00Z',
        webUrl: 'https://example.sharepoint.com/test',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
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
    siteId: createSmeared(mockSiteId),
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: '/test',
    fileName: 'test-file.docx',
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

    const { unit, unitRef } = await TestBed.solitary(FetchGraphPermissionsMapQuery)
      .mock<GraphApiService>(GraphApiService)
      .impl((stubFn) => ({
        ...stubFn(),
        getSiteName: vi.fn().mockResolvedValue(mockSiteName),
        getDriveItemPermissions: vi.fn(),
        getListItemPermissions: vi.fn(),
      }))
      .compile();

    query = unit;
    graphApiService = unitRef.get(GraphApiService) as unknown as GraphApiService;
  });

  describe('mapSharePointPermissionsToOurPermissions', () => {
    it('logs warning with redacted permissionInfo when all identity sets map to null', async () => {
      const mockPermission: SimplePermission = {
        id: 'perm-unparseable',
        grantedToIdentitiesV2: [
          {
            group: {
              id: 'group-1',
              displayName: 'Sensitive Group Name',
            },
          } as SimpleIdentitySet,
        ],
      };

      const items = [createMockDriveItem('item-1')];
      vi.mocked(graphApiService.getDriveItemPermissions).mockResolvedValue([mockPermission]);

      await query.run(createSmeared(mockSiteId), items);

      expect(loggerWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining('No parsable permissions for permission perm-unparseable'),
      );

      const warnCall = loggerWarnSpy.mock.calls.find((call) =>
        call[0].includes('No parsable permissions for permission perm-unparseable'),
      )?.[0];
      expect(warnCall).toBeDefined();

      const jsonStart = warnCall.indexOf('{');
      const jsonEnd = warnCall.lastIndexOf('}') + 1;
      const parsedInfo = JSON.parse(warnCall.substring(jsonStart, jsonEnd));

      expect(parsedInfo).toHaveProperty('itemId', 'item-1');
      expect(parsedInfo).toHaveProperty('id', 'perm-unparseable');
      expect(parsedInfo).toHaveProperty('grantedToIdentitiesV2');
      expect(parsedInfo.grantedToIdentitiesV2).toBeInstanceOf(Array);
      expect(parsedInfo.grantedToIdentitiesV2).toHaveLength(1);
      expect(parsedInfo.grantedToIdentitiesV2[0]).toHaveProperty('group');
      expect(parsedInfo.grantedToIdentitiesV2[0].group).toHaveProperty('id', 'group-1');
      expect(parsedInfo.grantedToIdentitiesV2[0].group).not.toHaveProperty('displayName');
      expect(warnCall).not.toContain('Sensitive Group Name');
    });

    it('logs warning with redacted permissionInfo excluding sensitive user data', async () => {
      const mockPermission: SimplePermission = {
        id: 'perm-user-data',
        grantedToIdentitiesV2: [
          {
            user: {
              id: 'user-1',
            },
          } as SimpleIdentitySet,
        ],
      };

      const items = [createMockDriveItem('item-1')];
      vi.mocked(graphApiService.getDriveItemPermissions).mockResolvedValue([mockPermission]);

      await query.run(createSmeared(mockSiteId), items);

      const warnCall = loggerWarnSpy.mock.calls.find((call) =>
        call[0].includes('No parsable permissions for permission perm-user-data'),
      )?.[0];
      expect(warnCall).toBeDefined();

      const jsonStart = warnCall.indexOf('{');
      const jsonEnd = warnCall.lastIndexOf('}') + 1;
      const parsedInfo = JSON.parse(warnCall.substring(jsonStart, jsonEnd));

      expect(parsedInfo.grantedToIdentitiesV2[0]).toHaveProperty('user');
      expect(parsedInfo.grantedToIdentitiesV2[0].user).toHaveProperty('id', 'user-1');
      expect(parsedInfo.grantedToIdentitiesV2[0].user).not.toHaveProperty('email');
      expect(warnCall).not.toContain('sensitive.email@example.com');
    });

    it('logs warning with redacted permissionInfo excluding sensitive siteUser data', async () => {
      const mockPermission: SimplePermission = {
        id: 'perm-siteuser-data',
        grantedToIdentitiesV2: [
          {
            siteUser: {
              id: 'site-user-1',
              loginName: 'sensitive\\loginname',
            },
          } as SimpleIdentitySet,
        ],
      };

      const items = [createMockDriveItem('item-1')];
      vi.mocked(graphApiService.getDriveItemPermissions).mockResolvedValue([mockPermission]);

      await query.run(createSmeared(mockSiteId), items);

      const warnCall = loggerWarnSpy.mock.calls.find((call) =>
        call[0].includes('No parsable permissions for permission perm-siteuser-data'),
      )?.[0];
      expect(warnCall).toBeDefined();

      const jsonStart = warnCall.indexOf('{');
      const jsonEnd = warnCall.lastIndexOf('}') + 1;
      const parsedInfo = JSON.parse(warnCall.substring(jsonStart, jsonEnd));

      expect(parsedInfo.grantedToIdentitiesV2[0]).toHaveProperty('siteUser');
      expect(parsedInfo.grantedToIdentitiesV2[0].siteUser).toHaveProperty('id', 'site-user-1');
      expect(parsedInfo.grantedToIdentitiesV2[0].siteUser).not.toHaveProperty('email');
      expect(parsedInfo.grantedToIdentitiesV2[0].siteUser).not.toHaveProperty('loginName');
      expect(warnCall).not.toContain('sensitive.siteuser@example.com');
      expect(warnCall).not.toContain('sensitive\\loginname');
    });

    it('logs warning with redacted permissionInfo including multiple identity sets with all sensitive data excluded', async () => {
      const mockPermission: SimplePermission = {
        id: 'perm-multiple-nulls',
        grantedToIdentitiesV2: [
          {
            group: {
              id: 'group-1',
              displayName: 'Sensitive Group 1',
            },
          } as SimpleIdentitySet,
          {
            user: {
              id: 'user-1',
              email: 'sensitive.user-unparsable',
            },
          } as SimpleIdentitySet,
          {
            siteUser: {
              id: 'site-user-1',
              loginName: 'sensitive\\login',
            },
          } as SimpleIdentitySet,
        ],
      };

      const items = [createMockDriveItem('item-1')];
      vi.mocked(graphApiService.getDriveItemPermissions).mockResolvedValue([mockPermission]);

      await query.run(createSmeared(mockSiteId), items);

      const warnCall = loggerWarnSpy.mock.calls.find((call) =>
        call[0].includes('No parsable permissions for permission perm-multiple-nulls'),
      )?.[0];
      expect(warnCall).toBeDefined();

      const jsonStart = warnCall.indexOf('{');
      const jsonEnd = warnCall.lastIndexOf('}') + 1;
      const parsedInfo = JSON.parse(warnCall.substring(jsonStart, jsonEnd));

      expect(parsedInfo).toHaveProperty('itemId', 'item-1');
      expect(parsedInfo.grantedToIdentitiesV2).toHaveLength(3);

      expect(parsedInfo.grantedToIdentitiesV2[0].group).toHaveProperty('id', 'group-1');
      expect(parsedInfo.grantedToIdentitiesV2[0].group).not.toHaveProperty('displayName');

      expect(parsedInfo.grantedToIdentitiesV2[1].user).toHaveProperty('id', 'user-1');
      expect(parsedInfo.grantedToIdentitiesV2[1].user).not.toHaveProperty('email');

      expect(parsedInfo.grantedToIdentitiesV2[2].siteUser).toHaveProperty('id', 'site-user-1');
      expect(parsedInfo.grantedToIdentitiesV2[2].siteUser).not.toHaveProperty('email');
      expect(parsedInfo.grantedToIdentitiesV2[2].siteUser).not.toHaveProperty('loginName');

      expect(warnCall).not.toContain('Sensitive Group 1');
      expect(warnCall).not.toContain('sensitive.user@example.com');
      expect(warnCall).not.toContain('sensitive.siteuser@example.com');
      expect(warnCall).not.toContain('sensitive\\login');
    });

    it('only includes id and optionally @odata.type in redacted identity values', async () => {
      const mockPermission: SimplePermission = {
        id: 'perm-structure-check',
        grantedToIdentitiesV2: [
          {
            group: {
              id: 'group-1',
              displayName: 'Test Group',
            },
          } as SimpleIdentitySet,
        ],
      };

      const items = [createMockDriveItem('item-1')];
      vi.mocked(graphApiService.getDriveItemPermissions).mockResolvedValue([mockPermission]);

      await query.run(createSmeared(mockSiteId), items);

      const warnCall = loggerWarnSpy.mock.calls.find((call) =>
        call[0].includes('No parsable permissions for permission perm-structure-check'),
      )?.[0];
      expect(warnCall).toBeDefined();

      const jsonStart = warnCall.indexOf('{');
      const jsonEnd = warnCall.lastIndexOf('}') + 1;
      const parsedInfo = JSON.parse(warnCall.substring(jsonStart, jsonEnd));

      const redactedGroup = parsedInfo.grantedToIdentitiesV2[0].group;
      const groupKeys = Object.keys(redactedGroup);
      expect(groupKeys.length).toBeGreaterThanOrEqual(1);
      expect(groupKeys).toContain('id');
      expect(groupKeys).not.toContain('displayName');
      if (groupKeys.includes('@odata.type')) {
        expect(groupKeys).toHaveLength(2);
      }
    });
  });
});
