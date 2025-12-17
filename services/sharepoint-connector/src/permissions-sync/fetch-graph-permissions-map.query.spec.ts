import { Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Config } from '../config';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { SimpleIdentitySet, SimplePermission } from '../microsoft-apis/graph/types/sharepoint.types';
import type { AnySharepointItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
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
    siteId: mockSiteId,
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
      .mock<ConfigService<Config, true>>(ConfigService)
      .impl((stubFn) => ({
        ...stubFn(),
        get: vi.fn().mockReturnValue(undefined),
      }))
      .compile();

    query = unit;
    graphApiService = unitRef.get(GraphApiService);
  });

  describe('mapSharePointPermissionsToOurPermissions', () => {
    it('logs warning with redacted permissionInfo when all identity sets map to null', async () => {
      const mockPermission: SimplePermission = {
        id: 'perm-unparseable',
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

      await query.run(mockSiteId, items);

      expect(loggerWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining('No parsable permissions for permission perm-unparseable'),
      );

      const warnCall = loggerWarnSpy.mock.calls.find((call) =>
        call[0].includes('No parsable permissions for permission perm-unparseable'),
      )?.[0];
      expect(warnCall).toBeDefined();
      expect(warnCall).toContain('perm-unparseable');

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
      expect(parsedInfo.grantedToIdentitiesV2[0].group).toEqual(
        expect.objectContaining({
          id: 'group-1',
        }),
      );
    });

    it('logs warning with redacted permissionInfo including multiple identity sets', async () => {
      const mockPermission: SimplePermission = {
        id: 'perm-multiple-nulls',
        grantedToIdentitiesV2: [
          {
            group: {
              id: 'group-1',
              displayName: 'Group 1',
            },
          } as SimpleIdentitySet,
          {
            user: {
              id: 'user-1',
              email: 'user@example.com',
            },
          } as SimpleIdentitySet,
        ],
      };

      const items = [createMockDriveItem('item-1')];
      vi.mocked(graphApiService.getDriveItemPermissions).mockResolvedValue([mockPermission]);

      await query.run(mockSiteId, items);

      expect(loggerWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining('No parsable permissions for permission perm-multiple-nulls'),
      );

      const warnCall = loggerWarnSpy.mock.calls.find((call) =>
        call[0].includes('No parsable permissions for permission perm-multiple-nulls'),
      )?.[0];
      expect(warnCall).toBeDefined();

      const jsonStart = warnCall.indexOf('{');
      const jsonEnd = warnCall.lastIndexOf('}') + 1;
      const parsedInfo = JSON.parse(warnCall.substring(jsonStart, jsonEnd));

      expect(parsedInfo).toHaveProperty('itemId', 'item-1');
      expect(parsedInfo.grantedToIdentitiesV2).toHaveLength(2);
      expect(parsedInfo.grantedToIdentitiesV2[0]).toHaveProperty('group');
      expect(parsedInfo.grantedToIdentitiesV2[0].group).toHaveProperty('id', 'group-1');
      expect(parsedInfo.grantedToIdentitiesV2[1]).toHaveProperty('user');
      expect(parsedInfo.grantedToIdentitiesV2[1].user).toHaveProperty('id', 'user-1');
    });
  });
});
