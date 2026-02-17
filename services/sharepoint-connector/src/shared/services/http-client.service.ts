import { Injectable } from '@nestjs/common';
import { Dispatcher, interceptors } from 'undici';
import { ProxyService } from '../../proxy';

@Injectable()
export class HttpClientService {
  private readonly httpAgent: Dispatcher;

  public constructor(private readonly proxyService: ProxyService) {
    const baseDispatcher = this.proxyService.getDispatcher({
      mode: 'for-external-only',
    });
    this.httpAgent = baseDispatcher.compose([interceptors.retry(), interceptors.redirect()]);
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
