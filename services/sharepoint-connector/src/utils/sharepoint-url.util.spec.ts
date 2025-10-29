import { describe, expect, it } from 'vitest';
import type { SharepointContentItem } from '../msgraph/types/sharepoint-content-item.interface';
import { buildIngetionItemKey, buildKnowledgeBaseUrl } from './sharepoint.util';

describe.skip('buildKnowledgeBaseUrl', () => {
  it('should build proper SharePoint URL for file in subfolder', () => {
    const file: SharepointContentItem = {
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
    const file: SharepointContentItem = {
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
    const file: SharepointContentItem = {
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
    const file: SharepointContentItem = {
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
    const file: SharepointContentItem = {
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
    const file: SharepointContentItem = {
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
    const file: SharepointContentItem = {
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

describe('buildFileDiffKey', () => {
  it('generates siteId/listId/itemId key for list items', () => {
    const listItem: SharepointContentItem = {
      itemType: 'listItem',
      item: {
        '@odata.etag': 'etag-list',
        id: 'list-item-123',
        eTag: 'etag-list',
        createdDateTime: '2023-01-01T00:00:00Z',
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        webUrl: 'https://tenant.sharepoint.com/sites/test/SitePages/Page1.aspx',
        fields: {
          '@odata.etag': 'etag-list',
          Title: 'Page 1',
        },
      },
      siteId: 'site-id-456',
      driveId: 'list-id-789',
      driveName: 'SitePages',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: 'https://tenant.sharepoint.com/sites/test/SitePages/Page1.aspx',
      fileName: 'Page 1',
    };

    const result = buildIngetionItemKey(listItem);
    expect(result).toBe('site-id-456/list-id-789/list-item-123');
  });

  it('generates itemId key for drive items', () => {
    const driveItem: SharepointContentItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: 'drive-item-id-xyz',
        name: 'document.pdf',
        webUrl: 'https://tenant.sharepoint.com/sites/test/_layouts/15/Doc.aspx',
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
      },
      siteId: 'site1',
      driveId: 'drive1',
      driveName: 'Documents',
      siteWebUrl: 'https://tenant.sharepoint.com/sites/test',
      folderPath: '/Documents',
      fileName: 'document.pdf',
    };

    const result = buildIngetionItemKey(driveItem);
    expect(result).toBe('site1/drive-item-id-xyz');
  });

  it('handles list items with complex IDs', () => {
    const listItem: SharepointContentItem = {
      itemType: 'listItem',
      item: {
        '@odata.etag': 'etag-complex',
        id: '01JWNC3IPYIDGEOH52ABAZMI7436JQOOJI',
        eTag: 'etag-complex',
        createdDateTime: '2023-01-01T00:00:00Z',
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        webUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG/SitePages/Analytics.aspx',
        fields: {
          '@odata.etag': 'etag-complex',
          Title: 'Analytics Dashboard',
        },
      },
      siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
      driveName: 'SitePages',
      siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG',
      folderPath: 'https://uniqueapp.sharepoint.com/sites/UniqueAG/SitePages/Analytics.aspx',
      fileName: 'Analytics Dashboard',
    };

    const result = buildIngetionItemKey(listItem);
    expect(result).toBe(
      'bd9c85ee-998f-4665-9c44-577cf5a08a66/b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq/01JWNC3IPYIDGEOH52ABAZMI7436JQOOJI',
    );
  });
});
