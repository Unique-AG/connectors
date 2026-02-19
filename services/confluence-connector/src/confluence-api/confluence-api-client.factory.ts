import { Injectable } from '@nestjs/common';
import type { ConfluenceConfig } from '../config';
import { ServiceRegistry } from '../tenant/service-registry';
import { CloudApiAdapter } from './adapters/cloud-api.adapter';
import { DataCenterApiAdapter } from './adapters/data-center-api.adapter';
import { ConfluenceApiClient } from './confluence-api-client';

const ATLASSIAN_API_GATEWAY = 'https://api.atlassian.com/ex/confluence';

@Injectable()
export class ConfluenceApiClientFactory {
  public constructor(private readonly serviceRegistry: ServiceRegistry) {}

  public create(config: ConfluenceConfig): ConfluenceApiClient {
    const adapter =
      config.instanceType === 'cloud'
        ? new CloudApiAdapter(`${ATLASSIAN_API_GATEWAY}/${config.cloudId}`, config.baseUrl)
        : new DataCenterApiAdapter(config.baseUrl);

    return new ConfluenceApiClient(adapter, config, this.serviceRegistry);
  }
}
