import { describe, expect, it } from 'vitest';
import type { PipelineItem } from '../msgraph/types/pipeline-item.interface';
import { buildKnowledgeBaseUrl } from './sharepoint-url.util';

describe('buildKnowledgeBaseUrl', () => {
  it('should build proper SharePoint URL for file in subfolder', () => {
    const file: PipelineItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: '1',
        name: 'test.pdf',
        webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
        size: 100,
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        parentReference: {
          driveType: 'documentLibrary',
          driveId: 'drive1',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Documents',
          siteId: 'site1',
        },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item1',
          eTag: 'etag1',
          createdDateTime: '2023-01-01T00:00:00Z',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: false,
            FileLeafRef: 'test.pdf',
            Modified: '2023-01-01T00:00:00Z',
            Created: '2023-01-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
          },
        },
      },
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '/Documents/Subfolder',
      fileName: 'test.pdf',
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/Documents/Subfolder/test.pdf');
  });

  it('should build proper SharePoint URL for file in root folder', () => {
    const file: PipelineItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: '1',
        name: 'test.pdf',
        webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
        size: 100,
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        parentReference: {
          driveType: 'documentLibrary',
          driveId: 'drive1',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/',
          siteId: 'site1',
        },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item1',
          eTag: 'etag1',
          createdDateTime: '2023-01-01T00:00:00Z',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: false,
            FileLeafRef: 'test.pdf',
            Modified: '2023-01-01T00:00:00Z',
            Created: '2023-01-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
          },
        },
      },
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '/',
      fileName: 'test.pdf',
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/test.pdf');
  });

  it('should build proper SharePoint URL for file in root folder with empty path', () => {
    const file: PipelineItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: '1',
        name: 'test.pdf',
        webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
        size: 100,
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        parentReference: {
          driveType: 'documentLibrary',
          driveId: 'drive1',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/',
          siteId: 'site1',
        },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item1',
          eTag: 'etag1',
          createdDateTime: '2023-01-01T00:00:00Z',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: false,
            FileLeafRef: 'test.pdf',
            Modified: '2023-01-01T00:00:00Z',
            Created: '2023-01-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
          },
        },
      },
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '',
      fileName: 'test.pdf',
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/test.pdf');
  });

  it('should handle siteWebUrl with trailing slash', () => {
    const file: PipelineItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: '1',
        name: 'test.pdf',
        webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
        size: 100,
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        parentReference: {
          driveType: 'documentLibrary',
          driveId: 'drive1',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Documents',
          siteId: 'site1',
        },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item1',
          eTag: 'etag1',
          createdDateTime: '2023-01-01T00:00:00Z',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: false,
            FileLeafRef: 'test.pdf',
            Modified: '2023-01-01T00:00:00Z',
            Created: '2023-01-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
          },
        },
      },
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test/',
      folderPath: '/Documents',
      fileName: 'test.pdf',
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/Documents/test.pdf');
  });

  it('should handle folderPath with leading slash', () => {
    const file: PipelineItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: '1',
        name: 'test.pdf',
        webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
        size: 100,
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        parentReference: {
          driveType: 'documentLibrary',
          driveId: 'drive1',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Documents/Subfolder',
          siteId: 'site1',
        },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item1',
          eTag: 'etag1',
          createdDateTime: '2023-01-01T00:00:00Z',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: false,
            FileLeafRef: 'test.pdf',
            Modified: '2023-01-01T00:00:00Z',
            Created: '2023-01-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
          },
        },
      },
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '/Documents/Subfolder',
      fileName: 'test.pdf',
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/Documents/Subfolder/test.pdf');
  });

  it('should handle folderPath without leading slash', () => {
    const file: PipelineItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: '1',
        name: 'test.pdf',
        webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
        size: 100,
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        parentReference: {
          driveType: 'documentLibrary',
          driveId: 'drive1',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Documents/Subfolder',
          siteId: 'site1',
        },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item1',
          eTag: 'etag1',
          createdDateTime: '2023-01-01T00:00:00Z',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: false,
            FileLeafRef: 'test.pdf',
            Modified: '2023-01-01T00:00:00Z',
            Created: '2023-01-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
          },
        },
      },
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: 'Documents/Subfolder',
      fileName: 'test.pdf',
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe('https://tenant.sharepoint.com/sites/test/Documents/Subfolder/test.pdf');
  });

  it('should URL encode special characters in folder names', () => {
    const file: PipelineItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: '1',
        name: 'test.pdf',
        webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
        size: 100,
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        parentReference: {
          driveType: 'documentLibrary',
          driveId: 'drive1',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Documents/Folder with spaces & special chars',
          siteId: 'site1',
        },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item1',
          eTag: 'etag1',
          createdDateTime: '2023-01-01T00:00:00Z',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx?sourcedoc=...',
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: false,
            FileLeafRef: 'test.pdf',
            Modified: '2023-01-01T00:00:00Z',
            Created: '2023-01-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
          },
        },
      },
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '/Documents/Folder with spaces & special chars',
      fileName: 'test.pdf',
    };

    const result = buildKnowledgeBaseUrl(file);
    expect(result).toBe(
      'https://tenant.sharepoint.com/sites/test/Documents/Folder%20with%20spaces%20%26%20special%20chars/test.pdf',
    );
  });
});
