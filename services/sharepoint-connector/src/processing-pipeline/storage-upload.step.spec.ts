import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StorageUploadStep } from './storage-upload.step';

vi.mock('undici', () => ({
  request: vi.fn(async () => ({ statusCode: 200 })),
}));

describe('StorageUploadStep', () => {
  it('uploads buffer to storage', async () => {
    const step = new StorageUploadStep();
    const context = {
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
    } as any;
    const result = await step.execute(context);
    expect(result.contentBuffer?.length).toBe(4);
  });
});
