import { vi } from 'vitest';

interface UploadCall {
  url: string;
  body: unknown;
  headers: Record<string, string>;
  timestamp: number;
}

export class MockHttpClientService {
  // biome-ignore lint/suspicious/noExplicitAny: Test mock response can be any shape
  public response: { statusCode: number; body: any } = {
    statusCode: 201,
    body: {},
  };

  private uploadCalls: UploadCall[] = [];

  public request = vi.fn().mockImplementation(async (options: { url?: string; path?: string; body?: unknown; headers?: Record<string, string>; method?: string }) => {
    // Track upload calls
    this.uploadCalls.push({
      url: options.url || options.path || '',
      body: options.body,
      headers: options.headers || {},
      timestamp: Date.now(),
    });

    return {
      statusCode: this.response.statusCode,
      body: {
        text: async () => JSON.stringify(this.response.body),
        json: async () => this.response.body,
      },
      headers: {},
    };
  });

  public getUploadCalls(): UploadCall[] {
    return [...this.uploadCalls];
  }

  public clear(): void {
    this.uploadCalls = [];
  }
}
