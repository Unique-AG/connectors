import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import type { ProcessingContext } from '../types/processing-context';
import { ContentRegistrationStep } from './content-registration.step';

describe('ContentRegistrationStep', () => {
  let step: ContentRegistrationStep;

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(ContentRegistrationStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => (k === 'uniqueApi.scopeId' ? 'scope-1' : undefined)),
      }))
      .mock(UniqueAuthService)
      .impl(() => ({ getToken: vi.fn().mockResolvedValue('unique-token') }))
      .mock(UniqueApiService)
      .impl(() => ({
        registerContent: vi.fn().mockResolvedValue({
          id: 'cid',
          writeUrl: 'https://upload',
          key: 'k',
          byteSize: 1,
          mimeType: 'application/pdf',
          ownerType: UniqueOwnerType.SCOPE,
          ownerId: 'o',
          readUrl: 'https://read',
          createdAt: new Date().toISOString(),
          internallyStoredAt: null,
          source: 'MICROSOFT_365_SHAREPOINT',
        }),
      }))
      .compile();
    step = unit;
  });

  it('registers content and updates context', async () => {
    const context: ProcessingContext = {
      correlationId: 'c1',
      fileId: 'f1',
      fileName: 'n',
      fileSize: 0,
      siteUrl: 'https://contoso.sharepoint.com/sites/Engineering',
      libraryName: 'lib',
      startTime: new Date(),
      metadata: {
        siteId: 'site',
        driveId: 'drive',
        mimeType: 'application/pdf',
        isFolder: false,
        listItemFields: {},
        driveName: 'Documents',
        folderPath: '/test',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
      },
    };
    const result = await step.execute(context);
    expect(result.uploadUrl).toBe('https://upload');
    expect(result.uniqueContentId).toBe('cid');
  });
});
