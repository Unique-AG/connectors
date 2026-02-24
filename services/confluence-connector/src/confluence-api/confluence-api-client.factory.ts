import { Injectable } from '@nestjs/common';
import type { ConfluenceConfig } from '../config';
import { ServiceRegistry } from '../tenant/service-registry';
import { CloudConfluenceApiClient } from './cloud-api-client';
import { ConfluenceApiClient } from './confluence-api-client';
import { DataCenterConfluenceApiClient } from './data-center-api-client';

@Injectable()
export class ConfluenceApiClientFactory {
  public constructor(private readonly serviceRegistry: ServiceRegistry) {}

  public create(config: ConfluenceConfig): ConfluenceApiClient {
    return config.instanceType === 'cloud'
      ? new CloudConfluenceApiClient(config, this.serviceRegistry)
      : new DataCenterConfluenceApiClient(config, this.serviceRegistry);
  }
}
