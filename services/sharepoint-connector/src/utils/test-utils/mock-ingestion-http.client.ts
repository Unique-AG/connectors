import { vi } from 'vitest';

export class MockIngestionHttpClient {
  public fileDiffResponse: Record<string, unknown> = {
    newFiles: ['item-1'],
    updatedFiles: [],
    movedFiles: [],
    deletedFiles: [],
  };

  public request = vi.fn().mockImplementation(async () => {
    return {
      statusCode: 200,
      body: {
        text: async () => JSON.stringify(this.fileDiffResponse),
        json: async () => this.fileDiffResponse,
      },
      headers: {},
    };
  });
}
