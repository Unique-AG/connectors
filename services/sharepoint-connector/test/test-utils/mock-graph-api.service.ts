import { Readable } from 'node:stream';
import { vi } from 'vitest';
import type { SimplePermission } from '../../src/microsoft-apis/graph/types/sharepoint.types';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../../src/microsoft-apis/graph/types/sharepoint-content-item.interface';

export class MockGraphApiService {
  public items: SharepointContentItem[] = [this.createDefaultItem()];
  public directories: SharepointDirectoryItem[] = [];
  public permissions: Record<string, SimplePermission[]> = {
    'item-1': [this.createDefaultPermission()],
  };

  // Mock config values for filtering (can be overridden in tests)
  public maxFileSizeToIngestBytes = 1048576; // 1MB default
  public allowedMimeTypes = [
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  ];

  public getAllSiteItems = vi
    .fn()
    .mockImplementation(async (_siteId: string, syncColumnName: string) => {
      // Filter items based on syncColumnName, size, and MIME type - mimicking real GraphApiService behavior
      const filteredItems = this.items.filter((item) => {
        // biome-ignore lint/suspicious/noExplicitAny: Mock needs to handle complex SharePoint types
        const syncValue = (item.item as any).listItem?.fields?.[syncColumnName];
        const size = ('size' in item.item && item.item.size) || 0;
        const mimeType = 'file' in item.item ? item.item.file?.mimeType : undefined;
        const isAspx = item.fileName?.toLowerCase().endsWith('.aspx');

        // Must have sync flag
        if (syncValue !== true) {
          return false;
        }

        // Check size limit
        if (size > this.maxFileSizeToIngestBytes) {
          return false;
        }

        // Check MIME type or ASPX
        if (!mimeType || (!this.allowedMimeTypes.includes(mimeType) && !isAspx)) {
          return false;
        }

        return true;
      });

      return {
        items: filteredItems,
        directories: [...this.directories],
      };
    });

  public getFileContentStream = vi.fn().mockImplementation(async () => {
    return Readable.from('mock-file-content');
  });

  public getSiteName = vi.fn().mockImplementation(async () => {
    return 'TestSite';
  });

  public getDriveItemPermissions = vi
    .fn()
    .mockImplementation(async (_driveId: string, itemId: string): Promise<SimplePermission[]> => {
      return this.permissions[itemId] ?? [];
    });

  public getListItemPermissions = vi
    .fn()
    .mockImplementation(
      async (_siteId: string, _listId: string, itemId: string): Promise<SimplePermission[]> => {
        return this.permissions[itemId] ?? [];
      },
    );

  public getGroupMembers = vi.fn().mockImplementation(async () => {
    return [];
  });

  public getGroupOwners = vi.fn().mockImplementation(async () => {
    return [];
  });

  // biome-ignore lint/suspicious/noExplicitAny: Test mock needs to accept any options structure
  private createDefaultItem(): any {
    return {
      itemType: 'driveItem',
      item: {
        '@odata.etag': '"etag-1"',
        id: 'item-1',
        name: 'test.pdf',
        webUrl: 'https://sharepoint.test.example.com/sites/TestSite/Documents/test.pdf',
        size: 1234,
        createdDateTime: '2025-01-01T00:00:00Z',
        lastModifiedDateTime: '2025-01-02T00:00:00Z',
        createdBy: {
          user: {
            email: 'author@example.com',
            id: 'author-1',
            displayName: 'Author One',
          },
        },
        parentReference: {
          driveType: 'documentLibrary',
          driveId: 'drive-1',
          id: 'parent-1',
          name: 'Documents',
          path: '/drives/drive-1/root:/Documents',
          siteId: '11111111-1111-4111-8111-111111111111',
        },
        file: {
          mimeType: 'application/pdf',
          hashes: {
            quickXorHash: 'abc123',
          },
        },
        listItem: {
          '@odata.etag': '"etag-1"',
          id: 'listItem-1',
          eTag: '"etag-1"',
          createdDateTime: '2025-01-01T00:00:00Z',
          lastModifiedDateTime: '2025-01-02T00:00:00Z',
          webUrl: 'https://sharepoint.test.example.com/sites/TestSite/Documents/test.pdf',
          createdBy: {
            user: {
              email: 'author@example.com',
              id: 'author-1',
              displayName: 'Author One',
            },
          },
          fields: {
            '@odata.etag': '"etag-1"',
            FileLeafRef: 'test.pdf',
            Modified: '2025-01-02T00:00:00Z',
            Created: '2025-01-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            FileSizeDisplay: '1 KB',
            ItemChildCount: '0',
            FolderChildCount: '0',
            SyncFlag: true,
            // biome-ignore lint/suspicious/noExplicitAny: Test fixture with dynamic fields
          } as any,
        } as any,
      } as any,
      siteId: '11111111-1111-4111-8111-111111111111',
      driveId: 'drive-1',
      driveName: 'Documents',
      folderPath: '/Documents',
      fileName: 'test.pdf',
    };
  }

  private createDefaultPermission(): SimplePermission {
    return {
      id: 'perm-1',
      grantedToV2: {
        user: {
          id: 'graph-user-1',
          email: 'user@example.com',
        },
      },
    };
  }
}
