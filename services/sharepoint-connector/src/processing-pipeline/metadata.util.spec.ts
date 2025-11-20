import { describe, expect, it } from 'vitest';
import { ModerationStatus } from '../constants/moderation-status.constants';
import type { DriveItem } from '../microsoft-apis/graph/types/sharepoint.types';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { buildSharepointMetadata } from './metadata.util';

describe('buildSharepointMetadata', () => {
  it('captures drive item metadata and custom fields', () => {
    const driveContentItem: SharepointContentItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: 'drive-id',
        name: 'document.pdf',
        webUrl: 'https://contoso.sharepoint.com/sites/site/documents/document.pdf',
        size: 1024,
        lastModifiedDateTime: '2025-10-10T00:00:00Z',
        parentReference: {
          driveType: 'documentLibrary',
          driveId: 'drive1',
          id: 'parent',
          name: 'Documents',
          path: '/drive/root:/folder',
          siteId: 'site1',
        },
        file: {
          mimeType: 'application/pdf',
          hashes: {
            quickXorHash: 'hash1',
          },
        },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item1',
          eTag: 'etag1',
          createdDateTime: '2025-10-01T00:00:00Z',
          lastModifiedDateTime: '2025-10-10T00:00:00Z',
          webUrl: 'https://contoso.sharepoint.com/sites/site/documents/document.pdf',
          createdBy: {
            user: {
              displayName: 'Drive Author',
              email: 'drive@example.com',
              id: 'user-id',
            },
          },
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: true,
            FileLeafRef: 'document.pdf',
            Modified: '2025-10-10T00:00:00Z',
            Created: '2025-10-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: 'author-lookup',
            EditorLookupId: 'editor-lookup',
            FileSizeDisplay: '1024',
            ItemChildCount: '0',
            FolderChildCount: '0',
            Page: 'Page Title',
            NewsTaf: 'news-value',
            Author: 'Field Author',
          },
        },
      },
      siteId: 'site1',
      siteWebUrl: 'https://contoso.sharepoint.com/sites/site1',
      driveId: 'drive1',
      driveName: 'Documents',
      folderPath: '/folder',
      fileName: 'document.pdf',
    };

    const metadata = buildSharepointMetadata(driveContentItem);

    expect(metadata.link).toContain('?web=1');
    expect(metadata.path).toBe('/folder');
    expect(metadata.filename).toBe('document.pdf');
    expect(metadata.driveName).toBe('Documents');
    expect(metadata.siteId).toBe('site1');
    expect(metadata.createdAt).toBe('2025-10-01T00:00:00Z');
    expect(metadata.modifiedAt).toBe('2025-10-10T00:00:00Z');
    expect(metadata.author).toBe('Drive Author');
    expect(metadata.page).toBe('Page Title');
    expect(metadata.newsTaf).toBe('news-value');
    const driveItemFields = (driveContentItem.item as DriveItem).listItem.fields;
    expect(metadata.fields).toEqual(driveItemFields);
  });

  it('captures list item metadata with fallback values', () => {
    const listContentItem: SharepointContentItem = {
      itemType: 'listItem',
      item: {
        id: 'list-item-1',
        webUrl: 'https://contoso.sharepoint.com/sites/site/page.aspx',
        lastModifiedDateTime: '2024-01-02T00:00:00Z',
        createdDateTime: '2024-01-01T00:00:00Z',
        createdBy: {
          user: {
            displayName: 'List Author',
            email: 'list@example.com',
            id: 'list-user',
          },
        },
        fields: {
          '@odata.etag': 'etag2',
          FinanceGPTKnowledge: false,
          _ModerationStatus: ModerationStatus.Approved,
          Title: 'Test Page',
          NewsTaf: 'news-page',
          Modified: '2024-01-02T00:00:00Z',
          Created: '2024-01-01T00:00:00Z',
          FileSizeDisplay: '512',
          FileLeafRef: 'page.aspx',
        },
      },
      siteId: 'site-2',
      siteWebUrl: 'https://contoso.sharepoint.com/sites/site-2',
      driveId: 'SitePages',
      driveName: 'SitePages',
      folderPath: '/',
      fileName: 'page.aspx',
    };

    const metadata = buildSharepointMetadata(listContentItem);

    expect(metadata.author).toBe('List Author');
    expect(metadata.page).toBe('Test Page');
    expect(metadata.newsTaf).toBe('news-page');
    expect(metadata.createdAt).toBe('2024-01-01T00:00:00Z');
    expect(metadata.modifiedAt).toBe('2024-01-02T00:00:00Z');
  });
});
