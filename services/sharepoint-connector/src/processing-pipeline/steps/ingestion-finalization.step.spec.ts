import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueAuthService } from '../../auth/unique-auth.service';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import type { ProcessingContext } from '../types/processing-context';
import { IngestionFinalizationStep } from './ingestion-finalization.step';

describe('IngestionFinalizationStep', () => {
  let step: IngestionFinalizationStep;

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(IngestionFinalizationStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => (k === 'uniqueApi.scopeId' ? 'scope-1' : undefined)),
      }))
      .mock(UniqueAuthService)
      .impl(() => ({ getToken: vi.fn().mockResolvedValue('unique-token') }))
      .mock(UniqueApiService)
      .impl(() => ({ finalizeIngestion: vi.fn().mockResolvedValue({ id: 'final-id' }) }))
      .compile();
    step = unit;
  });

  it('finalizes ingestion and updates metadata', async () => {
    const context: ProcessingContext = {
      correlationId: 'c1',
      fileId: 'f1',
      fileName: 'n',
      fileSize: 10,
      siteUrl: 'https://contoso.sharepoint.com/sites/Engineering',
      libraryName: 'lib',
      startTime: new Date(),
      metadata: {
        registration: {
          key: 'k',
          mimeType: 'application/pdf',
          ownerType: 'SCOPE',
          byteSize: 10,
          readUrl: 'https://read',
        },
      },
    };
    const result = await step.execute(context);
    expect(result.metadata.finalContentId).toBe('final-id');
  });
});
