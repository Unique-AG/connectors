import { vi } from 'vitest';

export class MockIngestionHttpClient {
  public request = vi.fn().mockResolvedValue({
    statusCode: 200,
    body: {
      text: async () =>
        JSON.stringify({
          newFiles: ['item-1'],
          updatedFiles: [],
          movedFiles: [],
          deletedFiles: [],
        }),
      json: async () => ({
        newFiles: ['item-1'],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      }),
    },
    headers: {},
  });
}
