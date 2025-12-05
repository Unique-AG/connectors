import { Injectable, OnModuleDestroy } from '@nestjs/common';
import { Agent, Dispatcher, interceptors } from 'undici';

@Injectable()
export class HttpClientService implements OnModuleDestroy {
  private readonly httpAgent: Dispatcher;

  public constructor() {
    const agent = new Agent();
    this.httpAgent = agent.compose([interceptors.retry(), interceptors.redirect()]);
  }

  public async onModuleDestroy(): Promise<void> {
    await this.httpAgent.close();
  }

  public async request(
    url: string | URL,
    options?: Omit<Dispatcher.RequestOptions, 'origin' | 'path'>,
  ): Promise<Dispatcher.ResponseData> {
    const urlObj = typeof url === 'string' ? new URL(url) : url;
    return await this.httpAgent.request({
      origin: urlObj.origin,
      path: urlObj.pathname + urlObj.search,
      method: options?.method || 'GET',
      ...options,
    });
  }
}
