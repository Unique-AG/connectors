import { describe, expect, it } from 'vitest';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { getItemUrl } from './sharepoint.util';
import { createSmeared } from './smeared';

describe('getItemUrl', () => {
  it('returns full URL when no rootScopeName is provided for driveItem', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: createSmeared('site123'),
      driveId: 'drive123',
      driveName: 'Shared Documents',
      folderPath: '/folder',
      fileName: 'report.pdf',
      item: {
        id: 'file1',
        listItem: {
          webUrl:
            'https://uniqueapp.sharepoint.com/sites/project/Shared Documents/folder/report.pdf',
        },
      },
    } as SharepointContentItem;

    const result = getItemUrl(item);

    expect(result).toBe(
      'https://uniqueapp.sharepoint.com/sites/project/Shared Documents/folder/report.pdf?web=1',
    );
  });

  it('appends web=1 parameter for driveItem', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: createSmeared('site123'),
      driveId: 'drive123',
      driveName: 'Shared Documents',
      folderPath: '/folder',
      fileName: 'report.pdf',
      item: {
        id: 'file1',
        listItem: {
          webUrl:
            'https://uniqueapp.sharepoint.com/sites/project/Shared Documents/folder/report.pdf',
        },
      },
    } as SharepointContentItem;

    const result = getItemUrl(item);

    expect(result).toBe(
      'https://uniqueapp.sharepoint.com/sites/project/Shared Documents/folder/report.pdf?web=1',
    );
  });

  it('appends web=1 parameter for listItem', () => {
    const item = {
      itemType: 'listItem' as const,
      siteId: createSmeared('site456'),
      driveId: 'drive456',
      driveName: 'SitePages',
      folderPath: '/',
      fileName: 'home.aspx',
      item: {
        id: 'list1',
        webUrl: 'https://contoso.sharepoint.com/sites/Engineering/SitePages/home.aspx',
      },
    } as SharepointContentItem;

    const result = getItemUrl(item);

    expect(result).toBe(
      'https://contoso.sharepoint.com/sites/Engineering/SitePages/home.aspx?web=1',
    );
  });

  it('handles different SharePoint domains correctly', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: createSmeared('site789'),
      driveId: 'drive789',
      driveName: 'Documents',
      folderPath: '/',
      fileName: 'budget.xlsx',
      item: {
        id: 'file1',
        listItem: {
          webUrl: 'https://company-dev.sharepoint.com/sites/team/Documents/budget.xlsx',
        },
      },
    } as SharepointContentItem;

    const result = getItemUrl(item);

    expect(result).toBe(
      'https://company-dev.sharepoint.com/sites/team/Documents/budget.xlsx?web=1',
    );
  });

  it('handles URLs with existing query parameters', () => {
    const item = {
      itemType: 'listItem' as const,
      siteId: createSmeared('site999'),
      driveId: 'drive999',
      driveName: 'news',
      folderPath: '/',
      fileName: 'article.aspx',
      item: {
        id: 'list1',
        webUrl: 'https://company.sharepoint.com/sites/marketing/news/article.aspx?id=123',
      },
    } as SharepointContentItem;

    const result = getItemUrl(item);

    expect(result).toBe(
      'https://company.sharepoint.com/sites/marketing/news/article.aspx?id=123&web=1',
    );
  });

  it('handles special characters in folder paths', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: createSmeared('site111'),
      driveId: 'drive111',
      driveName: 'Shared Documents',
      folderPath: '/2024 Q1',
      fileName: 'report.pdf',
      item: {
        id: 'file1',
        listItem: {
          webUrl: 'https://company.sharepoint.com/sites/team/Shared Documents/2024 Q1/report.pdf',
        },
      },
    } as SharepointContentItem;

    const result = getItemUrl(item);

    expect(result).toBe(
      'https://company.sharepoint.com/sites/team/Shared Documents/2024 Q1/report.pdf?web=1',
    );
  });

  it('handles URLs with existing query string', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: createSmeared('site222'),
      driveId: 'drive222',
      driveName: 'library',
      folderPath: '/path',
      fileName: 'file.txt',
      item: {
        id: 'file1',
        listItem: {
          webUrl: 'https://tenant.sharepoint.com/sites/site-name/library/path/file.txt?param=value',
        },
      },
    } as SharepointContentItem;

    const result = getItemUrl(item);

    expect(result).toBe(
      'https://tenant.sharepoint.com/sites/site-name/library/path/file.txt?param=value&web=1',
    );
  });
});
