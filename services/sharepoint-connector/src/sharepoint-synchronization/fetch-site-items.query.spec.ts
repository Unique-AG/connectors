import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { Smeared } from '../utils/smeared';
import { FetchSiteItemsQuery } from './fetch-site-items.query';
import { ScanListItemAttachmentsQuery } from './scan-list-item-attachments.query';

describe('FetchSiteItemsQuery', () => {
  let query: FetchSiteItemsQuery;
  let graphApiService: {
    getSiteLists: Mock;
    getAspxPagesForSite: Mock;
    getAllFilesForSite: Mock;
  };
  let scanListItemAttachmentsQuery: { execute: Mock };

  const siteId = new Smeared('site-1', false);
  const attachmentScanOptions = {
    itemNameColumnName: 'Title',
    subsiteFolderNames: ['Sub'],
  };
  const options = { ...attachmentScanOptions, scanListAttachments: true };
  const lists = [{ id: 'list-1', name: 'SitePages' }];
  const page = { itemType: 'listItem', fileName: 'Home' } as SharepointContentItem;
  const file = { itemType: 'driveItem', fileName: 'report.pdf' } as SharepointContentItem;
  const attachment = {
    itemType: 'listItemAttachment',
    fileName: 'policy.pdf',
  } as SharepointContentItem;
  const directory = { itemType: 'directory', fileName: 'Reports' } as SharepointDirectoryItem;

  beforeEach(async () => {
    graphApiService = {
      getSiteLists: vi.fn().mockResolvedValue(lists),
      getAspxPagesForSite: vi.fn().mockResolvedValue([page]),
      getAllFilesForSite: vi.fn().mockResolvedValue({ items: [file], directories: [directory] }),
    };
    scanListItemAttachmentsQuery = { execute: vi.fn().mockResolvedValue([attachment]) };

    const { unit } = await TestBed.solitary(FetchSiteItemsQuery)
      .mock(GraphApiService)
      .impl(() => graphApiService)
      .mock(ScanListItemAttachmentsQuery)
      .impl(() => scanListItemAttachmentsQuery)
      .compile();

    query = unit;
  });

  it('combines pages, drive files and list attachments of a site', async () => {
    const result = await query.execute(siteId, 'Sync', options);

    expect(result).toEqual({ items: [page, file, attachment], directories: [directory] });
  });

  it('loads the site lists once and hands them to the page and attachment scans', async () => {
    await query.execute(siteId, 'Sync', options);

    expect(graphApiService.getSiteLists).toHaveBeenCalledOnce();
    expect(graphApiService.getAspxPagesForSite).toHaveBeenCalledWith(siteId, 'Sync', lists);
    expect(graphApiService.getAllFilesForSite).toHaveBeenCalledWith(siteId, 'Sync');
    expect(scanListItemAttachmentsQuery.execute).toHaveBeenCalledWith(
      siteId,
      'Sync',
      attachmentScanOptions,
      lists,
    );
  });

  it('does not scan list attachments when the site does not enable them', async () => {
    const result = await query.execute(siteId, 'Sync', { ...options, scanListAttachments: false });

    expect(result).toEqual({ items: [page, file], directories: [directory] });
    expect(scanListItemAttachmentsQuery.execute).not.toHaveBeenCalled();
  });

  it.each([
    ['page', () => graphApiService.getAspxPagesForSite],
    ['drive file', () => graphApiService.getAllFilesForSite],
    ['list attachment', () => scanListItemAttachmentsQuery.execute],
  ])('fails the whole site when the %s scan fails', async (_scan, getScan) => {
    getScan().mockRejectedValue(new Error('scan failed'));

    await expect(query.execute(siteId, 'Sync', options)).rejects.toThrow('scan failed');
  });
});
