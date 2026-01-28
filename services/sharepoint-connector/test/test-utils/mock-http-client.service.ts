import { vi } from 'vitest';

export class MockHttpClientService {
  // biome-ignore lint/suspicious/noExplicitAny: Test mock response can be any shape
  public response: { statusCode: number; body: any } = {
    statusCode: 201,
    body: {},
  };

  public request = vi.fn().mockImplementation(async () => {
    return {
      statusCode: this.response.statusCode,
      body: {
        text: async () => JSON.stringify(this.response.body),
        json: async () => this.response.body,
      },
      headers: {},
    };
  });
}
