import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphApiService } from '../../msgraph/graph-api.service';
import type { ProcessingContext } from '../types/processing-context';
import { ContentFetchingStep } from './content-fetching.step';

describe('ContentFetchingStep', () => {
  let step: ContentFetchingStep;

  beforeEach(async () => {
    const mockConfig = { get: vi.fn(() => ['application/pdf']) } as unknown as ConfigService;
    const { unit } = await TestBed.solitary(ContentFetchingStep)
      .mock(ConfigService)
      .impl(() => mockConfig)
      .mock(GraphApiService)
      .impl(() => ({ downloadFileContent: vi.fn().mockResolvedValue(Buffer.from('abc')) }))
      .compile();
    step = unit;
  });

  it('fetches content and sets buffer and size', async () => {
    const context: ProcessingContext = {
      correlationId: 'c1',
      fileId: 'f1',
      fileName: 'n',
      fileSize: 0,
      siteUrl: '',
      libraryName: '',
      startTime: new Date(),
      metadata: {
        mimeType: 'application/pdf',
        driveId: 'drive1',
        isFolder: false,
        listItemFields: {},
        siteId: 'site1',
        driveName: 'Documents',
        folderPath: '/test',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
      },
    };
    const result = await step.execute(context);
    expect(result.fileSize).toBe(3);
    expect(Buffer.isBuffer(result.contentBuffer)).toBe(true);
  });
});
