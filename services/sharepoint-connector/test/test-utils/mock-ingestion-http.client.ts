import { vi } from 'vitest';
import type { FileDiffRequest } from '../../src/unique-api/unique-file-ingestion/unique-file-ingestion.types';

interface FileDiffCall {
  body: FileDiffRequest;
  timestamp: number;
}

export class MockIngestionHttpClient {
  // Mutable response (can be customized per test)
  public fileDiffResponse: Record<string, unknown> = {
    newFiles: ['item-1'],
    updatedFiles: [],
    movedFiles: [],
    deletedFiles: [],
  };

  // Track all file-diff calls
  private fileDiffCalls: FileDiffCall[] = [];

  public request = vi.fn().mockImplementation(async (options: { path: string; body: string; method?: string; headers?: Record<string, string> }) => {
    // Track the call if it's file-diff
    if (options.path === '/v2/content/file-diff') {
      this.fileDiffCalls.push({
        body: JSON.parse(options.body) as FileDiffRequest,
        timestamp: Date.now(),
      });
    }

    return {
      statusCode: 200,
      body: {
        text: async () => JSON.stringify(this.fileDiffResponse),
        json: async () => this.fileDiffResponse,
      },
      headers: {},
    };
  });

  // Query methods for tests
  public getFileDiffCalls(): FileDiffCall[] {
    return [...this.fileDiffCalls];
  }

  public clear(): void {
    this.fileDiffCalls = [];
  }
}
