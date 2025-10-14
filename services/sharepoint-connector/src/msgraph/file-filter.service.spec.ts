import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FileFilterService } from './file-filter.service';

describe('FileFilterService', () => {
  let service: FileFilterService;

  const mockDriveItem = (overrides: Partial<DriveItem> = {}): DriveItem => ({
    id: 'test-id',
    name: 'test.pdf',
    size: 1024,
    webUrl: 'https://sharepoint.example.com/test.pdf',
    lastModifiedDateTime: '2024-01-01T00:00:00Z',
    file: { mimeType: 'application/pdf' },
    listItem: {
      fields: {
        '@odata.etag': '"47cc40f8-ba1f-4100-9623-fcdf93073928,4"',
        FileLeafRef: 'test.pdf',
        Modified: '2024-01-01T00:00:00Z',
        MediaServiceImageTags: [],
        FinanceGPTKnowledge: true,
        id: '16599',
        ContentType: 'Dokument',
        Created: '2024-01-01T00:00:00Z',
        AuthorLookupId: '1704',
        EditorLookupId: '1704',
        _CheckinComment: '',
        LinkFilenameNoMenu: 'test.pdf',
        LinkFilename: 'test.pdf',
        DocIcon: 'pdf',
        FileSizeDisplay: '1024',
        ItemChildCount: '0',
        FolderChildCount: '0',
        _ComplianceFlags: '',
        _ComplianceTag: '',
        _ComplianceTagWrittenTime: '',
        _ComplianceTagUserId: '',
        _CommentCount: '',
        _LikeCount: '',
        _DisplayName: '',
        Edit: '0',
        _UIVersionString: '4.0',
        ParentVersionStringLookupId: '16599',
        ParentLeafNameLookupId: '16599',
      } as Record<string, unknown>,
    },
    ...overrides,
  });

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(FileFilterService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.syncColumnName') return 'FinanceGPTKnowledge';
          if (key === 'processing.allowedMimeTypes') return ['application/pdf', 'text/plain'];
          return undefined;
        }),
      }))
      .compile();

    service = unit;
  });

  it('returns true for valid syncable file', () => {
    const item = mockDriveItem();
    expect(service.isFileValidForIngestion(item)).toBe(true);
  });

  it('returns false for file without listItem fields', () => {
    const item = mockDriveItem({ listItem: undefined });
    expect(service.isFileValidForIngestion(item)).toBe(false);
  });

  it('returns false for empty file (0 bytes)', () => {
    const item = mockDriveItem({ size: 0 });
    expect(service.isFileValidForIngestion(item)).toBe(false);
  });

  it('returns false for file with undefined size', () => {
    const item = mockDriveItem({ size: undefined });
    expect(service.isFileValidForIngestion(item)).toBe(false);
  });

  it('returns false for file without sync flag', () => {
    const item = mockDriveItem({
      listItem: {
        fields: {
          '@odata.etag': '"47cc40f8-ba1f-4100-9623-fcdf93073928,4"',
          FileLeafRef: 'test.pdf',
          Modified: '2024-01-01T00:00:00Z',
          MediaServiceImageTags: [],
          FinanceGPTKnowledge: false, // This is the key difference - set to false
          id: '16599',
          ContentType: 'Dokument',
          Created: '2024-01-01T00:00:00Z',
          AuthorLookupId: '1704',
          EditorLookupId: '1704',
          _CheckinComment: '',
          LinkFilenameNoMenu: 'test.pdf',
          LinkFilename: 'test.pdf',
          DocIcon: 'pdf',
          FileSizeDisplay: '1024',
          ItemChildCount: '0',
          FolderChildCount: '0',
          _ComplianceFlags: '',
          _ComplianceTag: '',
          _ComplianceTagWrittenTime: '',
          _ComplianceTagUserId: '',
          _CommentCount: '',
          _LikeCount: '',
          _DisplayName: '',
          Edit: '0',
          _UIVersionString: '4.0',
          ParentVersionStringLookupId: '16599',
          ParentLeafNameLookupId: '16599',
        } as Record<string, unknown>,
      },
    });
    expect(service.isFileValidForIngestion(item)).toBe(false);
  });

  it('returns false for file with disallowed mime type', () => {
    const item = mockDriveItem({
      file: { mimeType: 'image/png' },
    });
    expect(service.isFileValidForIngestion(item)).toBe(false);
  });

  it('returns true for file with allowed text/plain mime type', () => {
    const item = mockDriveItem({
      file: { mimeType: 'text/plain' },
    });
    expect(service.isFileValidForIngestion(item)).toBe(true);
  });
});
