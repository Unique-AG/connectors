import { describe, expect, it, vi } from 'vitest';
import type { ProcessingContext } from '../types/processing-context';
import { StorageUploadStep } from './storage-upload.step';

vi.mock('undici', () => ({
  request: vi.fn(async () => ({ statusCode: 200 })),
}));

describe('StorageUploadStep', () => {
  it('uploads buffer to storage', async () => {
    const step = new StorageUploadStep();
    const context: ProcessingContext = {
      correlationId: 'c1',
      fileId: 'f1',
      fileName: 'n',
      fileSize: 0,
      siteUrl: '',
      libraryName: '',
      startTime: new Date(),
      metadata: { mimeType: 'application/pdf' },
      uploadUrl: 'https://upload.example.com',
      contentBuffer: Buffer.from('data'),
    };
    const result = await step.execute(context);
    expect(result.contentBuffer?.length).toBe(4);
  });
});
