import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import type { Config } from '../config';
import { ModerationStatus } from '../constants/moderation-status.constants';
import { FileFilterService } from '../microsoft-apis/graph/file-filter.service';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import type { ListItem } from '../microsoft-apis/graph/types/sharepoint.types';
import { SharepointRestClientService } from '../microsoft-apis/sharepoint-rest/sharepoint-rest-client.service';
import { SharepointRestError } from '../microsoft-apis/sharepoint-rest/sharepoint-rest-http.service';
import { MimeTypeResolverService } from '../shared/services/mime-type-resolver.service';
import { Smeared } from '../utils/smeared';
import {
  type ListItemAttachmentsScanOptions,
  ListViewThresholdExceededError,
  ScanListItemAttachmentsQuery,
  UnsupportedListReadSecurityError,
} from './scan-list-item-attachments.query';

describe('ScanListItemAttachmentsQuery', () => {
  let query: ScanListItemAttachmentsQuery;
  let authMode: 'certificate' | 'client-secret';
  let graphApiService: { getListItems: Mock; getSiteInfo: Mock };
  let restClient: { getListItemAttachments: Mock; getListReadSecurity: Mock };

  const maxFileSizeToIngestBytes = 10_000;
  const siteId = new Smeared('site-1', false);
  const scanOptions: ListItemAttachmentsScanOptions = {
    itemNameColumnName: 'Title',
    subsiteFolderNames: [],
  };
  const genericList = {
    id: 'list-1',
    name: 'Procedures',
    displayName: 'Procedures',
    list: { hidden: false, template: 'genericList' },
    columns: [
      { id: '1', name: 'Title', displayName: 'Title' },
      { id: '2', name: 'SyncToUnique', displayName: 'Sync' },
    ],
  };
  const listItem = {
    id: '4',
    webUrl: 'https://contoso.sharepoint.com/sites/Contoso/sub/Lists/Procedures/4_.000',
    lastModifiedDateTime: '2024-06-01T00:00:00Z',
    createdDateTime: '2024-01-01T00:00:00Z',
    createdBy: { user: { email: 'a@b.c', id: 'u', displayName: 'A' } },
    fields: { Title: 'Policy/HK', SyncToUnique: true, Attachments: true },
  } as unknown as ListItem;

  beforeEach(async () => {
    authMode = 'certificate';
    graphApiService = {
      getListItems: vi.fn().mockResolvedValue([listItem]),
      getSiteInfo: vi
        .fn()
        .mockResolvedValue({ siteName: new Smeared('Contoso/sub', false), managedPath: 'sites' }),
    };
    restClient = {
      getListItemAttachments: vi.fn().mockResolvedValue([
        {
          Name: '4',
          Files: [
            {
              Name: 'policy.pdf',
              Length: '2048',
              ServerRelativeUrl: '/sites/Contoso/sub/Lists/Procedures/Attachments/4/policy.pdf',
            },
          ],
        },
      ]),
      getListReadSecurity: vi.fn(),
    };

    const configService = {
      get: vi.fn((key: string) => {
        const values: Record<string, unknown> = {
          'sharepoint.baseUrl': 'https://contoso.sharepoint.com',
          'sharepoint.auth': { mode: authMode },
          'processing.allowedMimeTypes': ['application/pdf'],
          'processing.maxFileSizeToIngestBytes': maxFileSizeToIngestBytes,
          'processing.mimeTypeOverridesByExtension': {},
        };
        return values[key];
      }),
    } as unknown as ConfigService<Config, true>;
    const fileFilterService = new FileFilterService(
      configService,
      new MimeTypeResolverService(configService),
    );

    const { unit } = await TestBed.solitary(ScanListItemAttachmentsQuery)
      .mock(ConfigService)
      .impl(() => configService)
      .mock(GraphApiService)
      .impl(() => graphApiService)
      .mock(SharepointRestClientService)
      .impl(() => restClient)
      .mock(FileFilterService)
      .impl(() => fileFilterService)
      .compile();

    query = unit;
  });

  // biome-ignore lint/suspicious/noExplicitAny: Access private logger
  const getLogger = () => (query as any).logger;

  it('joins flagged items to the attachments of the web that owns the list', async () => {
    const result = await query.execute(siteId, 'Sync', scanOptions, [genericList] as never);

    expect(restClient.getListItemAttachments).toHaveBeenCalledWith(
      expect.objectContaining({ value: 'Contoso/sub' }),
      'sites',
      'list-1',
    );
    expect(result).toEqual([
      {
        itemType: 'listItemAttachment',
        item: listItem,
        siteId,
        driveId: 'list-1',
        driveName: 'Procedures',
        folderPath: '/Policy_HK',
        fileName: 'policy.pdf',
        attachment: {
          absoluteUrl:
            'https://contoso.sharepoint.com/sites/Contoso/sub/Lists/Procedures/Attachments/4/policy.pdf',
          size: 2048,
        },
      },
    ]);
  });

  describe('items in scope', () => {
    it.each([
      ['not flagged', { SyncToUnique: false }],
      ['pending approval', { _ModerationStatus: ModerationStatus.Pending }],
      ['rejected', { _ModerationStatus: ModerationStatus.Rejected }],
      ['without attachments', { Attachments: false }],
    ])('leaves out an item that is %s', async (_case, fields) => {
      graphApiService.getListItems.mockResolvedValue([
        { ...listItem, fields: { ...listItem.fields, ...fields } },
      ]);

      const result = await query.execute(siteId, 'Sync', scanOptions, [genericList] as never);

      expect(result).toEqual([]);
      expect(restClient.getListItemAttachments).not.toHaveBeenCalled();
    });

    it('takes an approved item of a list with content approval', async () => {
      graphApiService.getListItems.mockResolvedValue([
        {
          ...listItem,
          fields: { ...listItem.fields, _ModerationStatus: ModerationStatus.Approved },
        },
      ]);

      const result = await query.execute(siteId, 'Sync', scanOptions, [genericList] as never);

      expect(result).toHaveLength(1);
    });
  });

  it('leaves out attachments of a disallowed type, empty or over the size limit', async () => {
    restClient.getListItemAttachments.mockResolvedValue([
      {
        Name: '4',
        Files: [
          { Name: 'policy.pdf', Length: '2048' },
          { Name: 'photo.gif', Length: '2048' },
          { Name: 'empty.pdf', Length: '0' },
          { Name: 'huge.pdf', Length: String(maxFileSizeToIngestBytes + 1) },
        ].map((file) => ({
          ...file,
          ServerRelativeUrl: `/sites/Contoso/sub/Lists/Procedures/Attachments/4/${file.Name}`,
        })),
      },
    ]);

    const result = await query.execute(siteId, 'Sync', scanOptions, [genericList] as never);

    expect(result.map((entry) => entry.fileName)).toEqual(['policy.pdf']);
  });

  describe('list folder name', () => {
    const library = (name: string, displayName: string) => ({
      id: `library-${name}`,
      name,
      displayName,
      list: { hidden: false, template: 'documentLibrary' },
    });
    const syncedList = (id: string, displayName: string) => ({ ...genericList, id, displayName });

    const scanListFolderNames = async (lists: object[], options = scanOptions) => {
      const result = await query.execute(siteId, 'Sync', options, lists as never);
      return new Map(
        result.flatMap((entry) =>
          entry.itemType === 'listItemAttachment' ? [[entry.driveId, entry.driveName]] : [],
        ),
      );
    };

    it('uses the sanitized list title when no sibling folder has it', async () => {
      const names = await scanListFolderNames([
        syncedList('list-1', 'Q3/Notes'),
        library('Documents', 'Documents'),
      ]);

      expect(names.get('list-1')).toBe('Q3_Notes');
    });

    it('suffixes the list folder when a library URL name matches the list title', async () => {
      const result = await query.execute(siteId, 'Sync', scanOptions, [
        genericList,
        library('Procedures', 'Policies'),
      ] as never);

      expect(result[0]).toMatchObject({
        driveName: 'Procedures (List)',
        folderPath: '/Policy_HK',
      });
    });

    it('suffixes the list folder when a subsite folder matches the list title', async () => {
      const names = await scanListFolderNames([genericList], {
        ...scanOptions,
        subsiteFolderNames: ['Procedures'],
      });

      expect(names.get('list-1')).toBe('Procedures (List)');
    });

    it('keeps the list title when a sibling folder differs from it only in case', async () => {
      const names = await scanListFolderNames([genericList, library('procedures', 'Policies')]);

      expect(names.get('list-1')).toBe('Procedures');
    });

    it('keeps the list title when only a library title matches it', async () => {
      const names = await scanListFolderNames([
        genericList,
        library('Shared Documents', 'Procedures'),
      ]);

      expect(names.get('list-1')).toBe('Procedures');
    });

    it('falls back to the list id when the title sanitizes to nothing', async () => {
      const names = await scanListFolderNames([syncedList('list-1', '  ')]);

      expect(names.get('list-1')).toBe('list-1');
    });

    it('appends the list id to every list whose title sanitizes to the same name', async () => {
      const names = await scanListFolderNames([
        syncedList('list-1', 'A/B'),
        syncedList('list-2', 'A_B'),
      ]);

      expect(names.get('list-1')).toBe('A_B (list-1)');
      expect(names.get('list-2')).toBe('A_B (list-2)');
    });

    it('moves on to the list id when the suffixed name matches another list title', async () => {
      const names = await scanListFolderNames([
        syncedList('list-1', 'Docs'),
        syncedList('list-2', 'Docs (List)'),
        library('Docs', 'Documents'),
      ]);

      expect(names.get('list-1')).toBe('Docs (list-1)');
      expect(names.get('list-2')).toBe('Docs (List) (List)');
    });

    it('counts generic lists that are not synced when naming list folders', async () => {
      const unsyncedList = {
        ...genericList,
        id: 'list-2',
        name: 'Q3Notes',
        displayName: 'Q3:Notes',
        columns: [{ id: '1', name: 'Title', displayName: 'Title' }],
      };

      const names = await scanListFolderNames([syncedList('list-1', 'Q3/Notes'), unsyncedList]);

      expect([...names]).toEqual([['list-1', 'Q3_Notes (list-1)']]);
    });
  });

  describe('item folder name', () => {
    const scanItemFolderNames = async (titles: Array<[itemId: string, title: unknown]>) => {
      graphApiService.getListItems.mockResolvedValue(
        titles.map(([id, title]) => ({
          ...listItem,
          id,
          fields: { ...listItem.fields, Title: title },
        })),
      );
      restClient.getListItemAttachments.mockResolvedValue(
        titles.map(([id]) => ({
          Name: id,
          Files: [
            {
              Name: 'policy.pdf',
              Length: '2048',
              ServerRelativeUrl: `/sites/Contoso/sub/Lists/Procedures/Attachments/${id}/policy.pdf`,
            },
          ],
        })),
      );

      const result = await query.execute(siteId, 'Sync', scanOptions, [genericList] as never);
      return new Map(
        result.flatMap((entry) =>
          entry.itemType === 'listItemAttachment'
            ? [[entry.item.id, entry.folderPath.replace(/^\//, '')]]
            : [],
        ),
      );
    };

    it('replaces characters a scope name cannot contain and trims whitespace', async () => {
      const names = await scanItemFolderNames([
        ['1', 'Q3/Policy: "HK"'],
        ['2', '  Procedures  '],
      ]);

      expect(names.get('1')).toBe('Q3_Policy_ _HK_');
      expect(names.get('2')).toBe('Procedures');
    });

    it('stringifies numeric column values', async () => {
      const names = await scanItemFolderNames([['1', 2026]]);

      expect(names.get('1')).toBe('2026');
    });

    it('uses the item id when the column value is empty, missing or not a scalar', async () => {
      const names = await scanItemFolderNames([
        ['1', '   '],
        ['2', undefined],
        ['3', { text: 'nope' }],
      ]);

      expect(names.get('1')).toBe('1');
      expect(names.get('2')).toBe('2');
      expect(names.get('3')).toBe('3');
    });

    it('appends the item id to every item that shares a name', async () => {
      const names = await scanItemFolderNames([
        ['1', 'Policy'],
        ['2', 'Policy'],
        ['3', 'Other'],
      ]);

      expect(names.get('1')).toBe('Policy (1)');
      expect(names.get('2')).toBe('Policy (2)');
      expect(names.get('3')).toBe('Other');
    });

    it('treats names that sanitize to the same value as duplicates', async () => {
      const names = await scanItemFolderNames([
        ['1', 'A/B'],
        ['2', 'A:B'],
      ]);

      expect(names.get('1')).toBe('A_B (1)');
      expect(names.get('2')).toBe('A_B (2)');
    });

    it('keeps names that differ only in case as separate folders', async () => {
      const names = await scanItemFolderNames([
        ['1', 'Policy'],
        ['2', 'policy'],
      ]);

      expect(names.get('1')).toBe('Policy');
      expect(names.get('2')).toBe('policy');
    });

    it('appends the id to an item whose name equals a generated name', async () => {
      const names = await scanItemFolderNames([
        ['1', 'A'],
        ['2', 'A'],
        ['3', 'A (1)'],
      ]);

      expect(names.get('1')).toBe('A (1)');
      expect(names.get('2')).toBe('A (2)');
      expect(names.get('3')).toBe('A (1) (3)');
    });

    it('returns the same names regardless of item order', async () => {
      const forward = await scanItemFolderNames([
        ['1', 'Policy'],
        ['2', 'Policy'],
      ]);
      const reversed = await scanItemFolderNames([
        ['2', 'Policy'],
        ['1', 'Policy'],
      ]);

      expect(forward).toEqual(reversed);
    });
  });

  it('does not scan library templates', async () => {
    const result = await query.execute(siteId, 'Sync', scanOptions, [
      { ...genericList, list: { hidden: false, template: 'pictureLibrary' } },
    ] as never);

    expect(result).toEqual([]);
    expect(graphApiService.getListItems).not.toHaveBeenCalled();
    expect(restClient.getListItemAttachments).not.toHaveBeenCalled();
  });

  it('skips list attachments when authentication is not certificate-based', async () => {
    authMode = 'client-secret';
    const warnSpy = vi.spyOn(getLogger(), 'warn');

    const result = await query.execute(siteId, 'Sync', scanOptions, [genericList] as never);

    expect(result).toEqual([]);
    expect(graphApiService.getListItems).not.toHaveBeenCalled();
    expect(restClient.getListItemAttachments).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('client secret'));
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('will be deleted'));
  });

  it('does not warn about client-secret auth when no list has the sync column', async () => {
    authMode = 'client-secret';
    const warnSpy = vi.spyOn(getLogger(), 'warn');

    const result = await query.execute(siteId, 'NotOnThisList', scanOptions, [
      genericList,
    ] as never);

    expect(result).toEqual([]);
    expect(warnSpy).not.toHaveBeenCalled();
    expect(graphApiService.getSiteInfo).not.toHaveBeenCalled();
    expect(graphApiService.getListItems).not.toHaveBeenCalled();
  });

  it('aborts before reading items when a list allows users to read only their own items', async () => {
    restClient.getListReadSecurity.mockResolvedValue(2);
    graphApiService.getListItems.mockResolvedValue([]);

    await expect(
      query.execute(siteId, 'Sync', scanOptions, [genericList] as never),
    ).rejects.toBeInstanceOf(UnsupportedListReadSecurityError);
    expect(restClient.getListReadSecurity).toHaveBeenCalledWith(
      expect.objectContaining({ value: 'Contoso/sub' }),
      'sites',
      'list-1',
    );
    expect(graphApiService.getListItems).not.toHaveBeenCalled();
    expect(restClient.getListItemAttachments).not.toHaveBeenCalled();
  });

  it('aborts when a list exceeds the list view threshold', async () => {
    restClient.getListItemAttachments.mockRejectedValue(
      new SharepointRestError(
        'Failed to request SharePoint endpoint: 500',
        500,
        '-2147024860, Microsoft.SharePoint.SPQueryThrottledException',
      ),
    );

    await expect(
      query.execute(siteId, 'Sync', scanOptions, [genericList] as never),
    ).rejects.toThrow(
      expect.objectContaining({
        name: 'ListViewThresholdExceededError',
        message: expect.stringContaining('(list-1)'),
      }),
    );
  });

  it('passes other SharePoint REST errors through', async () => {
    const restError = new SharepointRestError(
      'Failed to request SharePoint endpoint: 404',
      404,
      '-2130575322, Microsoft.SharePoint.SPException',
    );
    restClient.getListItemAttachments.mockRejectedValue(restError);

    await expect(query.execute(siteId, 'Sync', scanOptions, [genericList] as never)).rejects.toBe(
      restError,
    );
  });

  it('smears the list name in the list view threshold error', () => {
    const error = new ListViewThresholdExceededError(new Smeared('Procedures', true), 'list-1');

    expect(error.message).not.toContain('Procedures');
    expect(error.message).toContain('(list-1)');
  });

  it('skips a list that does not have the item name column', async () => {
    const warnSpy = vi.spyOn(getLogger(), 'warn');

    const result = await query.execute(
      siteId,
      'Sync',
      { ...scanOptions, itemNameColumnName: 'MissingColumn' },
      [genericList] as never,
    );

    expect(result).toEqual([]);
    expect(restClient.getListItemAttachments).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('MissingColumn'));
  });
});
