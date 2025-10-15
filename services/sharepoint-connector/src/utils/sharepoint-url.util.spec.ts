import { describe, expect, it } from 'vitest';
import type { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';
import { buildKnowledgeBaseUrl } from './sharepoint-url.util';

describe('buildKnowledgeBaseUrl', () => {
  it('should build proper SharePoint URL for file in subfolder', () => {
    const file: EnrichedDriveItem = {
      id: '1',
      name: 'test.pdf',
      size: 100,
      webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '/Documents/Subfolder',
      lastModifiedDateTime: '2023-01-01T00:00:00Z',
      listItem: {
        id: 'item1',
        fields: {},
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
      },
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/Documents/Subfolder/test.pdf');
  });

  it('should build proper SharePoint URL for file in root folder', () => {
    const file: EnrichedDriveItem = {
      id: '1',
      name: 'test.pdf',
      size: 100,
      webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '/',
      lastModifiedDateTime: '2023-01-01T00:00:00Z',
      listItem: {
        id: 'item1',
        fields: {},
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
      },
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/test.pdf');
  });

  it('should build proper SharePoint URL for file in root folder with empty path', () => {
    const file: EnrichedDriveItem = {
      id: '1',
      name: 'test.pdf',
      size: 100,
      webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '',
      lastModifiedDateTime: '2023-01-01T00:00:00Z',
      listItem: {
        id: 'item1',
        fields: {},
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
      },
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/test.pdf');
  });

  it('should handle siteWebUrl with trailing slash', () => {
    const file: EnrichedDriveItem = {
      id: '1',
      name: 'test.pdf',
      size: 100,
      webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test/',
      folderPath: '/Documents',
      lastModifiedDateTime: '2023-01-01T00:00:00Z',
      listItem: {
        id: 'item1',
        fields: {},
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
      },
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/Documents/test.pdf');
  });

  it('should handle folderPath with leading slash', () => {
    const file: EnrichedDriveItem = {
      id: '1',
      name: 'test.pdf',
      size: 100,
      webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '/Documents/Subfolder',
      lastModifiedDateTime: '2023-01-01T00:00:00Z',
      listItem: {
        id: 'item1',
        fields: {},
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
      },
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/Documents/Subfolder/test.pdf');
  });

  it('should handle folderPath without leading slash', () => {
    const file: EnrichedDriveItem = {
      id: '1',
      name: 'test.pdf',
      size: 100,
      webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: 'Documents/Subfolder',
      lastModifiedDateTime: '2023-01-01T00:00:00Z',
      listItem: {
        id: 'item1',
        fields: {},
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
      },
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/Documents/Subfolder/test.pdf');
  });

  it('should URL encode special characters in folder names', () => {
    const file: EnrichedDriveItem = {
      id: '1',
      name: 'test.pdf',
      size: 100,
      webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '/Documents/Folder with spaces & special chars',
      lastModifiedDateTime: '2023-01-01T00:00:00Z',
      listItem: {
        id: 'item1',
        fields: {},
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
      },
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe(
      'https://tenant.sharepoint.com/sites/test/Documents/Folder%20with%20spaces%20%26%20special%20chars/test.pdf',
    );
  });
});
