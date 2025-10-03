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
    file: { mimeType: 'application/pdf' },
    listItem: {
      fields: {
        Sync: true,
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
          if (key === 'sharepoint.syncColumnName') return 'Sync';
          if (key === 'sharepoint.allowedMimeTypes') return ['application/pdf', 'text/plain'];
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
          Sync: false,
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
