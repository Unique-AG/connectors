import { describe, expect, it } from 'vitest';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { buildSharepointFileKey, buildSharepointPartialKey, getItemUrl } from './sharepoint.util';

describe('buildSharepointFileKey', () => {
  it('should build scope-based key when scopeId is provided', () => {
    const result = buildSharepointFileKey({
      scopeId: 'scope123',
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '/folder/subfolder',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('sharepoint_scope_scope123_file789');
  });

  it('should build path-based key when scopeId is null', () => {
    const result = buildSharepointFileKey({
      scopeId: null,
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '/folder/subfolder',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/folder/subfolder/document.docx');
  });

  it('should build path-based key when scopeId is undefined', () => {
    const result = buildSharepointFileKey({
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '/folder/subfolder',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/folder/subfolder/document.docx');
  });

  it('should handle empty folderPath', () => {
    const result = buildSharepointFileKey({
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/document.docx');
  });

  it('should handle root folderPath', () => {
    const result = buildSharepointFileKey({
      siteId: 'site456',
      driveName: 'Documents',
      folderPath: '/',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/document.docx');
  });

  it('should trim slashes from inputs', () => {
    const result = buildSharepointFileKey({
      siteId: '/site456/',
      driveName: '/Documents/',
      folderPath: '/folder/subfolder/',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('site456/Documents/folder/subfolder/document.docx');
  });

  it('should handle extra spaces in inputs', () => {
    const result = buildSharepointFileKey({
      siteId: '  site456  ',
      driveName: '  Documents  ',
      folderPath: '  /folder/subfolder  ',
      fileId: 'file789',
      fileName: '  document.docx  ',
    });

    expect(result).toBe('site456/Documents/folder/subfolder/document.docx');
  });

  it('should filter out empty segments', () => {
    const result = buildSharepointFileKey({
      siteId: '',
      driveName: 'Documents',
      folderPath: '',
      fileId: 'file789',
      fileName: 'document.docx',
    });

    expect(result).toBe('Documents/document.docx');
  });
});

describe('buildSharepointPartialKey', () => {
  it('should build scope-based partial key when scopeId is provided', () => {
    const result = buildSharepointPartialKey({
      scopeId: 'scope123',
      siteId: 'site456',
    });

    expect(result).toBe('sharepoint_scope_scope123_');
  });

  it('should build path-based partial key when scopeId is null', () => {
    const result = buildSharepointPartialKey({
      scopeId: null,
      siteId: 'site456',
    });

    expect(result).toBe('site456');
  });

  it('should build path-based partial key when scopeId is undefined', () => {
    const result = buildSharepointPartialKey({
      siteId: 'site456',
    });

    expect(result).toBe('site456');
  });

  it('should trim slashes from siteId', () => {
    const result = buildSharepointPartialKey({
      siteId: '/site456/',
    });

    expect(result).toBe('site456');
  });
});

describe('getItemUrl', () => {
  it('returns full URL when no rootScopeName is provided for driveItem', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: 'site123',
      siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/project',
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

  it('simplifies path structure with custom scope for driveItem', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: 'site123',
      siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/project',
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

    const result = getItemUrl(item, 'my-custom-scope');

    expect(result).toBe('my-custom-scope/project/Shared Documents/folder/report.pdf?web=1');
  });

  it('simplifies path structure with custom scope for listItem', () => {
    const item = {
      itemType: 'listItem' as const,
      siteId: 'site456',
      siteWebUrl: 'https://contoso.sharepoint.com/sites/Engineering',
      driveId: 'drive456',
      driveName: 'SitePages',
      folderPath: '/',
      fileName: 'home.aspx',
      item: {
        id: 'list1',
        webUrl: 'https://contoso.sharepoint.com/sites/Engineering/SitePages/home.aspx',
      },
    } as SharepointContentItem;

    const result = getItemUrl(item, 'knowledge-base');

    expect(result).toBe('knowledge-base/Engineering/SitePages/home.aspx?web=1');
  });

  it('handles different SharePoint domains correctly', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: 'site789',
      siteWebUrl: 'https://company-dev.sharepoint.com/sites/team',
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

    const result = getItemUrl(item, 'finance-scope');

    expect(result).toBe('finance-scope/team/Documents/budget.xlsx?web=1');
  });

  it('preserves query parameters when simplifying path', () => {
    const item = {
      itemType: 'listItem' as const,
      siteId: 'site999',
      siteWebUrl: 'https://company.sharepoint.com/sites/marketing',
      driveId: 'drive999',
      driveName: 'news',
      folderPath: '/',
      fileName: 'article.aspx',
      item: {
        id: 'list1',
        webUrl: 'https://company.sharepoint.com/sites/marketing/news/article.aspx?id=123',
      },
    } as SharepointContentItem;

    const result = getItemUrl(item, 'content-root');

    expect(result).toBe('content-root/marketing/news/article.aspx?id=123&web=1');
  });

  it('handles special characters in folder paths', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: 'site111',
      siteWebUrl: 'https://company.sharepoint.com/sites/team',
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

    const result = getItemUrl(item, 'archive');

    expect(result).toBe('archive/team/Shared Documents/2024 Q1/report.pdf?web=1');
  });

  it('removes sites prefix correctly', () => {
    const item = {
      itemType: 'driveItem' as const,
      siteId: 'site222',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/site-name',
      driveId: 'drive222',
      driveName: 'library',
      folderPath: '/path',
      fileName: 'file.txt',
      item: {
        id: 'file1',
        listItem: {
          webUrl: 'https://tenant.sharepoint.com/sites/site-name/library/path/file.txt',
        },
      },
    } as SharepointContentItem;

    const result = getItemUrl(item, 'root');

    expect(result).toBe('root/site-name/library/path/file.txt?web=1');
  });
});
