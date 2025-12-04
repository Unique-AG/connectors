import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_MAX_FILE_SIZE_BYTES } from '../../constants/defaults.constants';
import { ModerationStatus } from '../../constants/moderation-status.constants';
import { FileFilterService } from './file-filter.service';
import type { DriveItem } from './types/sharepoint.types';

describe('FileFilterService', () => {
  let service: FileFilterService;

  const mockDriveItem = (overrides: Partial<DriveItem> = {}): DriveItem => {
    const base: DriveItem = {
      '@odata.etag': 'etag1',
      id: 'test-id',
      name: 'test.pdf',
      size: 1024,
      webUrl: 'https://sharepoint.example.com/test.pdf',
      createdDateTime: '2024-01-01T00:00:00Z',
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      createdBy: {
        user: {
          email: 'test@example.com',
          id: 'user-1',
          displayName: 'Test User',
        },
      },
      parentReference: {
        driveType: 'documentLibrary',
        driveId: 'drive-1',
        id: 'parent-1',
        name: 'Documents',
        path: '/drive/root:/',
        siteId: 'site-1',
      },
      file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
      listItem: {
        '@odata.etag': '"47cc40f8-ba1f-4100-9623-fcdf93073928,4"',
        id: 'item-1',
        eTag: 'etag1',
        createdDateTime: '2024-01-01T00:00:00Z',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
        webUrl: 'https://sharepoint.example.com/test.pdf',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        fields: {
          '@odata.etag': '"47cc40f8-ba1f-4100-9623-fcdf93073928,4"',
          FinanceGPTKnowledge: true,
          FileLeafRef: 'test.pdf',
          Modified: '2024-01-01T00:00:00Z',
          Created: '2024-01-01T00:00:00Z',
          ContentType: 'Dokument',
          AuthorLookupId: '1704',
          EditorLookupId: '1704',
          FileSizeDisplay: '12345',
          ItemChildCount: '0',
          FolderChildCount: '0',
        },
      },
    };

    const result: DriveItem = { ...base, ...overrides };

    if (overrides.file) {
      result.file = {
        mimeType: overrides.file.mimeType ?? 'application/pdf',
        hashes: { quickXorHash: 'hash1' },
      };
    }

    if (overrides.listItem) {
      result.listItem = { ...base.listItem, ...overrides.listItem };
      if (overrides.listItem.fields) {
        result.listItem.fields = { ...base.listItem.fields, ...overrides.listItem.fields };
      }
    }

    return result;
  };

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(FileFilterService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.syncColumnName') return 'FinanceGPTKnowledge';
          if (key === 'processing.allowedMimeTypes') return ['application/pdf', 'text/plain'];
          if (key === 'processing.maxFileSizeBytes') return DEFAULT_MAX_FILE_SIZE_BYTES;
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
    const baseItem = mockDriveItem();
    const item = mockDriveItem({
      listItem: {
        ...baseItem.listItem,
        fields: {
          ...baseItem.listItem.fields,
          FinanceGPTKnowledge: false,
        },
      },
    });
    expect(service.isFileValidForIngestion(item)).toBe(false);
  });

  it('returns false for file with disallowed mime type', () => {
    const item = mockDriveItem({
      file: { mimeType: 'image/png', hashes: { quickXorHash: 'hash1' } },
    });
    expect(service.isFileValidForIngestion(item)).toBe(false);
  });

  it('returns true for file with allowed text/plain mime type', () => {
    const item = mockDriveItem({
      file: { mimeType: 'text/plain', hashes: { quickXorHash: 'hash1' } },
    });
    expect(service.isFileValidForIngestion(item)).toBe(true);
  });

  it('returns true for ASPX file with allowed MIME type', () => {
    const item = mockDriveItem({
      name: 'test.aspx',
      file: { mimeType: 'text/html', hashes: { quickXorHash: 'hash1' } },
    });
    expect(service.isFileValidForIngestion(item)).toBe(true);
  });

  it('returns true for ASPX file with disallowed MIME type', () => {
    const item = mockDriveItem({
      name: 'test.aspx',
      file: { mimeType: 'image/png', hashes: { quickXorHash: 'hash1' } },
    });
    expect(service.isFileValidForIngestion(item)).toBe(true);
  });

  it('returns true for ASPX file without MIME type', () => {
    const item = mockDriveItem({
      name: 'test.aspx',
      file: { mimeType: 'text/html', hashes: { quickXorHash: 'hash1' } },
    });
    expect(service.isFileValidForIngestion(item)).toBe(true);
  });

  it('returns false for file with .aspx in middle of name but not extension', () => {
    const item = mockDriveItem({
      name: 'test.aspx.doc',
      file: { mimeType: 'application/msword', hashes: { quickXorHash: 'hash1' } },
    });
    expect(service.isFileValidForIngestion(item)).toBe(false);
  });

  it('returns false for file ending with .aspx but without file property', () => {
    const item = mockDriveItem({
      name: 'test.aspx',
      file: undefined,
    });
    expect(service.isFileValidForIngestion(item)).toBe(false);
  });

  describe('isAspxFileValidForIngestion', () => {
    const createFieldsObject = (overrides?: Record<string, unknown>) => ({
      '@odata.etag': 'etag1',
      FinanceGPTKnowledge: true,
      _ModerationStatus: ModerationStatus.Approved,
      Title: 'test.aspx',
      FileSizeDisplay: '1024',
      FileLeafRef: 'test.aspx',
      ...overrides,
    });

    it('returns true for valid ASPX file with all required fields', () => {
      const fields = createFieldsObject();
      expect(service.isListItemValidForIngestion(fields)).toBe(true);
    });

    it('returns false for non-ASPX file', () => {
      const fields = createFieldsObject({ FileLeafRef: 'test.pdf' });
      expect(service.isListItemValidForIngestion(fields)).toBe(false);
    });

    it('returns false for ASPX file without sync flag', () => {
      const fields = createFieldsObject({ FinanceGPTKnowledge: false });
      expect(service.isListItemValidForIngestion(fields)).toBe(false);
    });

    it('returns false for ASPX file with undefined sync flag', () => {
      const fields = createFieldsObject({ FinanceGPTKnowledge: undefined });
      expect(service.isListItemValidForIngestion(fields)).toBe(false);
    });

    it('returns false for ASPX file that is not approved', () => {
      const fields = createFieldsObject({ _ModerationStatus: ModerationStatus.Rejected });
      expect(service.isListItemValidForIngestion(fields)).toBe(false);
    });

    it('returns false for ASPX file with pending moderation status', () => {
      const fields = createFieldsObject({ _ModerationStatus: ModerationStatus.Pending });
      expect(service.isListItemValidForIngestion(fields)).toBe(false);
    });

    it('returns false for ASPX file with undefined moderation status', () => {
      const fields = createFieldsObject({ _ModerationStatus: undefined });
      expect(service.isListItemValidForIngestion(fields)).toBe(false);
    });

    it('returns false for file without FileLeafRef', () => {
      const fields = createFieldsObject({ FileLeafRef: undefined });
      expect(service.isListItemValidForIngestion(fields)).toBe(false);
    });

    it('returns false for file exceeding maxFileSizeBytes', () => {
      const item = mockDriveItem({ size: DEFAULT_MAX_FILE_SIZE_BYTES + 1 });
      expect(service.isFileValidForIngestion(item)).toBe(false);
    });

    it('returns true for file at maxFileSizeBytes limit', () => {
      const item = mockDriveItem({ size: DEFAULT_MAX_FILE_SIZE_BYTES });
      expect(service.isFileValidForIngestion(item)).toBe(true);
    });

    it('returns true for file below maxFileSizeBytes limit', () => {
      const item = mockDriveItem({ size: 1048576 });
      expect(service.isFileValidForIngestion(item)).toBe(true);
    });
  });
});
