import { Injectable } from '@nestjs/common';
import { ConfluenceAuth } from '../auth/confluence-auth';
import type { ConfluenceConfig } from '../config';
import { ProxyService } from '../proxy';
import { ServiceRegistry } from '../tenant/service-registry';
import { RateLimitedHttpClient } from '../utils/rate-limited-http-client';
import { CloudConfluenceApiClient } from './cloud-api-client';
import { type ApiClientOptions, ConfluenceApiClient } from './confluence-api-client';
import { DataCenterConfluenceApiClient } from './data-center-api-client';

@Injectable()
export class ConfluenceApiClientFactory {
  public constructor(
    private readonly serviceRegistry: ServiceRegistry,
    private readonly proxyService: ProxyService,
  ) {}

  public create(
    config: ConfluenceConfig,
    options: ApiClientOptions = { attachmentsEnabled: false },
  ): ConfluenceApiClient {
    const confluenceAuth = this.serviceRegistry.getService(ConfluenceAuth);
    const dispatcher = this.proxyService.getDispatcher({ mode: 'always' });
    const httpClient = new RateLimitedHttpClient(config.apiRateLimitPerMinute, dispatcher);

    return config.instanceType === 'cloud'
      ? new CloudConfluenceApiClient(config, confluenceAuth, httpClient, options)
      : new DataCenterConfluenceApiClient(config, confluenceAuth, httpClient, options);
  }
}
