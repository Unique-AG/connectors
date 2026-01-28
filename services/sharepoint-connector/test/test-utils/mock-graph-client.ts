import { Readable } from 'node:stream';
import type { Drive, List } from '@microsoft/microsoft-graph-types';
import type {
  DriveItem,
  ListItem,
  SimplePermission,
} from '../../src/microsoft-apis/graph/types/sharepoint.types';

/**
 * Mock Microsoft Graph Client that simulates SharePoint API responses.
 *
 * This mock replaces the actual @microsoft/microsoft-graph-client to allow
 * testing GraphApiService without making real HTTP calls to Microsoft Graph API.
 *
 * Key design decisions:
 * - Returns RAW SharePoint data (not filtered)
 * - Production GraphApiService + FileFilterService handle filtering
 * - Tests can configure data per scenario
 * - Supports fluent API like real Graph Client
 */
export class MockGraphClient {
  // Test data - public so tests can configure
  public siteLists: List[] = [this.createDefaultSitePagesList()];
  public drives: Drive[] = [this.createDefaultDrive()];
  public driveItems: DriveItem[] = [this.createDefaultDriveItem()];
  public listItems: ListItem[] = [];
  public permissions: Record<string, SimplePermission[]> = {
    'item-1': [this.createDefaultPermission()],
  };
  public groupMembers: unknown[] = [];
  public groupOwners: unknown[] = [];
  public fileContentStreams: Record<string, Readable> = {};

  public api(url: string) {
    return new MockGraphRequest(url, this);
  }

  private createDefaultSitePagesList(): List {
    return {
      id: 'sitepages-list-1',
      name: 'SitePages',
      displayName: 'Site Pages',
    };
  }

  private createDefaultDrive(): Drive {
    return {
      id: 'drive-1',
      name: 'Documents',
      driveType: 'documentLibrary',
    };
  }

  private createDefaultDriveItem(): DriveItem {
    return {
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
        },
      },
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

/**
 * Fluent API request builder that mimics Microsoft Graph Client's request API.
 */
class MockGraphRequest {
  public constructor(
    private url: string,
    private client: MockGraphClient,
  ) {}

  public select(_fields: string) {
    return this;
  }

  public top(_count: number) {
    return this;
  }

  public filter(_query: string) {
    return this;
  }

  public expand(_fields: string) {
    return this;
  }

  public async get() {
    // Route based on URL pattern - simulates SharePoint API endpoints

    // Site lists: /sites/{siteId}/lists
    if (this.url.match(/\/sites\/[^/]+\/lists$/)) {
      return { value: this.client.siteLists };
    }

    // Site drives: /sites/{siteId}/drives
    if (this.url.match(/\/sites\/[^/]+\/drives$/)) {
      return { value: this.client.drives };
    }

    // Drive items: /drives/{driveId}/items/{itemId}/children
    if (this.url.match(/\/drives\/[^/]+\/items\/[^/]+\/children$/)) {
      return { value: this.client.driveItems };
    }

    // List items: /sites/{siteId}/lists/{listId}/items
    if (this.url.match(/\/sites\/[^/]+\/lists\/[^/]+\/items$/)) {
      return { value: this.client.listItems };
    }

    // Drive item permissions: /drives/{driveId}/items/{itemId}/permissions
    if (this.url.match(/\/drives\/[^/]+\/items\/([^/]+)\/permissions$/)) {
      const itemId = this.url.match(/\/drives\/[^/]+\/items\/([^/]+)\/permissions$/)?.[1];
      return { value: itemId ? this.client.permissions[itemId] || [] : [] };
    }

    // List item permissions: /sites/{siteId}/lists/{listId}/items/{itemId}/permissions
    if (this.url.match(/\/sites\/[^/]+\/lists\/[^/]+\/items\/([^/]+)\/permissions$/)) {
      const itemId = this.url.match(/\/items\/([^/]+)\/permissions$/)?.[1];
      return { value: itemId ? this.client.permissions[itemId] || [] : [] };
    }

    // Group members: /groups/{groupId}/members
    if (this.url.match(/\/groups\/[^/]+\/members$/)) {
      return { value: this.client.groupMembers };
    }

    // Group owners: /groups/{groupId}/owners
    if (this.url.match(/\/groups\/[^/]+\/owners$/)) {
      return { value: this.client.groupOwners };
    }

    // Site info: /sites/{siteId}
    if (
      this.url.match(/\/sites\/[^/]+$/) &&
      !this.url.includes('/lists') &&
      !this.url.includes('/drives')
    ) {
      return {
        webUrl: 'https://sharepoint.test.example.com/sites/TestSite',
        displayName: 'Test Site',
      };
    }

    // File content stream: /drives/{driveId}/items/{itemId}/content
    if (this.url.match(/\/drives\/[^/]+\/items\/([^/]+)\/content$/)) {
      const itemId = this.url.match(/\/drives\/[^/]+\/items\/([^/]+)\/content$/)?.[1];
      if (itemId && this.client.fileContentStreams[itemId]) {
        return this.client.fileContentStreams[itemId];
      }
      return Readable.from('mock-file-content');
    }

    // Default: empty response
    return { value: [] };
  }

  public async getStream() {
    // Used for file content downloads - must return ReadableStream (web API)
    if (this.url.match(/\/drives\/[^/]+\/items\/([^/]+)\/content$/)) {
      const itemId = this.url.match(/\/drives\/[^/]+\/items\/([^/]+)\/content$/)?.[1];
      if (itemId && this.client.fileContentStreams[itemId]) {
        // Convert Node.js Readable to web ReadableStream
        const readable = this.client.fileContentStreams[itemId];
        return Readable.toWeb(readable);
      }
    }
    // Default: return web ReadableStream
    return Readable.toWeb(Readable.from('mock-file-content'));
  }
}
