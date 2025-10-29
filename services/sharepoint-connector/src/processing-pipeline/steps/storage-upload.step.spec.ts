import { describe, expect, it, vi } from 'vitest';
import type { DriveItem } from '../../microsoft-apis/graph/types/sharepoint.types';
import type { ProcessingContext } from '../types/processing-context';
import { StorageUploadStep } from './storage-upload.step';

vi.mock('undici', () => ({
  request: vi.fn(async () => ({ statusCode: 200 })),
}));

describe('StorageUploadStep', () => {
  it('uploads buffer to storage', async () => {
    const step = new StorageUploadStep();

    const driveItem: DriveItem = {
      '@odata.etag': 'etag1',
      id: 'f1',
      name: 'file.pdf',
      webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      size: 1024,
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      parentReference: {
        driveType: 'documentLibrary',
        driveId: 'drive1',
        id: 'parent1',
        name: 'Documents',
        path: '/drive/root:/test',
        siteId: 'site1',
      },
      file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
      listItem: {
        '@odata.etag': 'etag1',
        id: 'item1',
        eTag: 'etag1',
        createdDateTime: '2024-01-01T00:00:00Z',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
        webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
        fields: {
          '@odata.etag': 'etag1',
          FinanceGPTKnowledge: false,
          FileLeafRef: 'file.pdf',
          Modified: '2024-01-01T00:00:00Z',
          Created: '2024-01-01T00:00:00Z',
          ContentType: 'Document',
          AuthorLookupId: '1',
          EditorLookupId: '1',
          ItemChildCount: '0',
          FolderChildCount: '0',
        },
      },
    };

    const context: ProcessingContext = {
      correlationId: 'c1',
      startTime: new Date(),
      knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      mimeType: 'application/pdf',
      pipelineItem: {
        itemType: 'driveItem',
        item: driveItem,
        siteId: 'site1',
        siteWebUrl: 'https://contoso.sharepoint.com/sites/Engineering',
        driveId: 'drive1',
        driveName: 'Documents',
        folderPath: '/test',
        fileName: 'file.pdf',
      },
      uploadUrl: 'https://upload.example.com',
      contentBuffer: Buffer.from('data'),
    };

    const result = await step.execute(context);
    expect(result.contentBuffer?.length).toBe(4);
  });
});
