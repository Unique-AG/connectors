import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SharepointAuthService } from '../auth/sharepoint-auth.service';
import { UniqueAuthService } from '../auth/unique-auth.service';
import { TokenValidationStep } from './token-validation.step';

describe('TokenValidationStep', () => {
  let step: TokenValidationStep;

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(TokenValidationStep)
      .mock(SharepointAuthService)
      .impl(() => ({ getToken: vi.fn().mockResolvedValue('graph-token') }))
      .mock(UniqueAuthService)
      .impl(() => ({ getToken: vi.fn().mockResolvedValue('unique-token') }))
      .compile();
    step = unit;
  });

  it('validates tokens and sets metadata', async () => {
    const context = {
      correlationId: 'c1',
      fileId: 'f1',
      fileName: 'n',
      fileSize: 0,
      siteUrl: '',
      libraryName: '',
      startTime: new Date(),
      metadata: {},
    } as const as any;
    const result = await step.execute(context);
    const tokens = result.metadata.tokens as unknown as {
      graphApiToken: string;
      uniqueApiToken: string;
    };
    expect(tokens.graphApiToken).toBe('graph-token');
    expect(tokens.uniqueApiToken).toBe('unique-token');
  });
});
