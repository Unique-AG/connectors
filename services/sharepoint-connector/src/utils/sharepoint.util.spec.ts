import { describe, expect, it } from 'vitest';
import type { AnySharepointItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { getUniqueParentPathFromItem, getUniquePathFromItem } from './sharepoint.util';

function createDriveItem(listItemWebUrl: string, itemWebUrl?: string): AnySharepointItem {
  return {
    itemType: 'driveItem',
    siteId: 'site123',
    driveId: 'drive123',
    driveName: 'Shared Documents',
    folderPath: '/path/to/file',
    fileName: 'document.pdf',
    item: {
      id: 'file123',
      webUrl: itemWebUrl || 'https://tenant.sharepoint.com/sites/TestSite/_layouts/15/Doc.aspx',
      listItem: {
        webUrl: listItemWebUrl,
        id: 'list123',
        '@odata.etag': 'etag123',
        eTag: 'etag123',
        createdDateTime: '2024-01-01T00:00:00Z',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
        fields: {},
      },
    },
  } as AnySharepointItem;
}

function createListItem(webUrl: string): AnySharepointItem {
  return {
    itemType: 'listItem',
    siteId: 'site456',
    driveId: 'drive456',
    driveName: 'SitePages',
    folderPath: '/news',
    fileName: 'article.aspx',
    item: {
      id: 'list456',
      webUrl,
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      createdDateTime: '2024-01-01T00:00:00Z',
      fields: {},
    },
  } as AnySharepointItem;
}

function createDirectoryItem(webUrl: string): AnySharepointItem {
  return {
    itemType: 'directory',
    siteId: 'site789',
    driveId: 'drive789',
    driveName: 'Shared Documents',
    folderPath: '/2024/Q1',
    fileName: '',
    item: {
      id: 'folder789',
      webUrl,
      listItem: {
        webUrl: '',
        id: 'list789',
        '@odata.etag': 'etag789',
        eTag: 'etag789',
        createdDateTime: '2024-01-01T00:00:00Z',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
        fields: {},
      },
    },
  } as AnySharepointItem;
}

describe('getUniqueParentPathFromItem', () => {
  it('returns parent path for driveItem with listItem.webUrl and strips siteName', () => {
    const item = createDriveItem(
      'https://dogfoodindustries.sharepoint.com/sites/TestTeamSite/Shared%20Documents/lorand%27s%20files/acer-pdf/Extensa%205635_5635g_5635z_5635zg_5235%20(ba50_mv).pdf',
    );

    const result = getUniqueParentPathFromItem(item, 'MyScope');

    expect(result).toBe("/MyScope/Shared Documents/lorand's files/acer-pdf");
  });

  it('returns parent path for driveItem falling back to item.webUrl when listItem.webUrl is missing', () => {
    const item = createDriveItem(
      '',
      'https://contoso.sharepoint.com/sites/Engineering/Documents/project/docs/readme.pdf',
    );

    const result = getUniqueParentPathFromItem(item, 'EngineeringScope');

    expect(result).toBe('/EngineeringScope/Documents/project/docs');
  });

  it('returns parent path for listItem', () => {
    const item = createListItem(
      'https://company.sharepoint.com/sites/Marketing/SitePages/article.aspx',
    );

    const result = getUniqueParentPathFromItem(item, 'MarketingScope');

    expect(result).toBe('/MarketingScope/SitePages');
  });

  it('returns parent path for directory item', () => {
    const item = createDirectoryItem(
      'https://tenant.sharepoint.com/sites/Team/Shared Documents/2024/Q1',
    );

    const result = getUniqueParentPathFromItem(item, 'TeamScope');

    expect(result).toBe('/TeamScope/Shared Documents/2024');
  });

  it('handles root-level item returning drive path', () => {
    const item = createDriveItem(
      'https://company.sharepoint.com/sites/Project/Documents/root-file.pdf',
    );

    const result = getUniqueParentPathFromItem(item, 'ProjectScope');

    expect(result).toBe('/ProjectScope/Documents');
  });

  it('handles URLs with special characters and encoding', () => {
    const item = createDriveItem(
      'https://tenant.sharepoint.com/sites/TestSite/Shared%20Documents/folder%20with%20spaces/sub-folder/file%20(1).pdf',
    );

    const result = getUniqueParentPathFromItem(item, 'TestScope');

    expect(result).toBe('/TestScope/Shared Documents/folder with spaces/sub-folder');
  });

  it('throws error when rootScopeName is empty', () => {
    const item = createDriveItem(
      'https://company.sharepoint.com/sites/Site/Library/path/to/file/document.pdf',
    );

    expect(() => getUniqueParentPathFromItem(item, '')).toThrow('rootPath cannot be empty');
  });

  it('handles nested paths with multiple levels', () => {
    const item = createDriveItem(
      'https://tenant.sharepoint.com/sites/DeepSite/Documents/level1/level2/level3/level4/deep-file.pdf',
    );

    const result = getUniqueParentPathFromItem(item, 'DeepScope');

    expect(result).toBe('/DeepScope/Documents/level1/level2/level3/level4');
  });

  it('handles rootPath with trailing slash', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniqueParentPathFromItem(item, 'ProjectScope/');

    expect(result).toBe('/ProjectScope/Documents');
  });

  it('handles rootPath with leading slash', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniqueParentPathFromItem(item, '/ProjectScope');

    expect(result).toBe('/ProjectScope/Documents');
  });

  it('handles rootPath with both leading and trailing slashes', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniqueParentPathFromItem(item, '/ProjectScope/');

    expect(result).toBe('/ProjectScope/Documents');
  });

  it('handles rootPath with multiple consecutive slashes', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniqueParentPathFromItem(item, 'Project//Scope');

    expect(result).toBe('/Project/Scope/Documents');
  });

  it('handles rootPath with multiple slashes at start and end', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniqueParentPathFromItem(item, '///ProjectScope///');

    expect(result).toBe('/ProjectScope/Documents');
  });

  it('handles rootPath with multiple slashes in the middle', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniqueParentPathFromItem(item, 'Project///Scope//Test');

    expect(result).toBe('/Project/Scope/Test/Documents');
  });
});

describe('getUniquePathFromItem', () => {
  it('returns full path for driveItem with listItem.webUrl', () => {
    const item = createDriveItem(
      'https://dogfoodindustries.sharepoint.com/sites/TestTeamSite/Shared%20Documents/lorand%27s%20files/acer-pdf/Extensa%205635_5635g_5635z_5635zg_5235%20(ba50_mv).pdf',
    );

    const result = getUniquePathFromItem(item, 'MyScope');

    expect(result).toBe(
      "/MyScope/Shared Documents/lorand's files/acer-pdf/Extensa 5635_5635g_5635z_5635zg_5235 (ba50_mv).pdf",
    );
  });

  it('returns full path for driveItem falling back to item.webUrl when listItem.webUrl is missing', () => {
    const item = createDriveItem(
      '',
      'https://contoso.sharepoint.com/sites/Engineering/Documents/project/docs/readme.pdf',
    );

    const result = getUniquePathFromItem(item, 'EngineeringScope');

    expect(result).toBe('/EngineeringScope/Documents/project/docs/readme.pdf');
  });

  it('returns full path for listItem', () => {
    const item = createListItem(
      'https://company.sharepoint.com/sites/Marketing/SitePages/article.aspx',
    );

    const result = getUniquePathFromItem(item, 'MarketingScope');

    expect(result).toBe('/MarketingScope/SitePages/article.aspx');
  });

  it('returns full path for directory item', () => {
    const item = createDirectoryItem(
      'https://tenant.sharepoint.com/sites/Team/Shared Documents/2024/Q1',
    );

    const result = getUniquePathFromItem(item, 'TeamScope');

    expect(result).toBe('/TeamScope/Shared Documents/2024/Q1');
  });

  it('handles root-level item returning drive path with filename', () => {
    const item = createDriveItem(
      'https://company.sharepoint.com/sites/Project/Documents/root-file.pdf',
    );

    const result = getUniquePathFromItem(item, 'ProjectScope');

    expect(result).toBe('/ProjectScope/Documents/root-file.pdf');
  });

  it('handles URLs with special characters and encoding', () => {
    const item = createDriveItem(
      'https://tenant.sharepoint.com/sites/TestSite/Shared%20Documents/folder%20with%20spaces/sub-folder/file%20(1).pdf',
    );

    const result = getUniquePathFromItem(item, 'TestScope');

    expect(result).toBe('/TestScope/Shared Documents/folder with spaces/sub-folder/file (1).pdf');
  });

  it('throws error when rootScopeName is empty', () => {
    const item = createDriveItem(
      'https://company.sharepoint.com/sites/Site/Library/path/to/file/document.pdf',
    );

    expect(() => getUniquePathFromItem(item, '')).toThrow('rootPath cannot be empty');
  });

  it('handles nested paths with multiple levels', () => {
    const item = createDriveItem(
      'https://tenant.sharepoint.com/sites/DeepSite/Documents/level1/level2/level3/level4/deep-file.pdf',
    );

    const result = getUniquePathFromItem(item, 'DeepScope');

    expect(result).toBe('/DeepScope/Documents/level1/level2/level3/level4/deep-file.pdf');
  });

  it('handles rootPath with trailing slash', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniquePathFromItem(item, 'ProjectScope/');

    expect(result).toBe('/ProjectScope/Documents/file.pdf');
  });

  it('handles rootPath with leading slash', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniquePathFromItem(item, '/ProjectScope');

    expect(result).toBe('/ProjectScope/Documents/file.pdf');
  });

  it('handles rootPath with both leading and trailing slashes', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniquePathFromItem(item, '/ProjectScope/');

    expect(result).toBe('/ProjectScope/Documents/file.pdf');
  });

  it('handles rootPath with multiple consecutive slashes', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniquePathFromItem(item, 'Project//Scope');

    expect(result).toBe('/Project/Scope/Documents/file.pdf');
  });

  it('handles rootPath with multiple slashes at start and end', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniquePathFromItem(item, '///ProjectScope///');

    expect(result).toBe('/ProjectScope/Documents/file.pdf');
  });

  it('handles rootPath with multiple slashes in the middle', () => {
    const item = createDriveItem('https://company.sharepoint.com/sites/Project/Documents/file.pdf');

    const result = getUniquePathFromItem(item, 'Project///Scope//Test');

    expect(result).toBe('/Project/Scope/Test/Documents/file.pdf');
  });
});
