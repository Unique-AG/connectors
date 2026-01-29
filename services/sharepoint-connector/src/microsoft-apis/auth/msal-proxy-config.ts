import type { INetworkModule, NetworkRequestOptions, NetworkResponse } from '@azure/msal-node';
import { type Dispatcher, fetch as undiciFetch } from 'undici';

export class ProxiedMsalNetworkClient implements INetworkModule {
  public constructor(private readonly dispatcher: Dispatcher) {}

  public async sendGetRequestAsync<T>(
    url: string,
    options?: NetworkRequestOptions,
  ): Promise<NetworkResponse<T>> {
    const response = await undiciFetch(url, {
      method: 'GET',
      headers: options?.headers as Record<string, string>,
      dispatcher: this.dispatcher,
    });

    return {
      headers: Object.fromEntries(response.headers.entries()),
      body: (await response.json()) as T,
      status: response.status,
    };
  }

  public async sendPostRequestAsync<T>(
    url: string,
    options?: NetworkRequestOptions,
  ): Promise<NetworkResponse<T>> {
    const response = await undiciFetch(url, {
      method: 'POST',
      headers: options?.headers as Record<string, string>,
      body: options?.body,
      dispatcher: this.dispatcher,
    });

    return {
      headers: Object.fromEntries(response.headers.entries()),
      body: (await response.json()) as T,
      status: response.status,
    };
  }
}
