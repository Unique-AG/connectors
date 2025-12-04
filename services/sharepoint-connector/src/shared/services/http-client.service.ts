import { Injectable, OnModuleDestroy } from '@nestjs/common';
import { Agent, Dispatcher, interceptors } from 'undici';

@Injectable()
export class HttpClientService implements OnModuleDestroy {
  private readonly httpAgent: Dispatcher;

  public constructor() {
    const interceptorsInCallingOrder = [
      interceptors.redirect({
        maxRedirections: 10,
      }),
      interceptors.retry({
        maxRetries: 3,
        minTimeout: 1_000,
        errorCodes: [
          'ETIMEDOUT',
          'ECONNRESET',
          'ECONNREFUSED',
          'ENOTFOUND',
          'ENETDOWN',
          'ENETUNREACH',
          'EHOSTDOWN',
          'EHOSTUNREACH',
          'EPIPE',
          'UND_ERR_SOCKET',
        ],
      }),
    ];

    const agent = new Agent({
      bodyTimeout: 60_000,
      headersTimeout: 30_000,
      connectTimeout: 15_000,
    });
    this.httpAgent = agent.compose(interceptorsInCallingOrder.reverse());
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
