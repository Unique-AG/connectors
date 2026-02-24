import { Injectable } from '@nestjs/common';
import { ConfluenceAuth } from '../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../config';
import { ServiceRegistry } from '../tenant/service-registry';
import { CloudConfluenceApiClient } from './cloud-api-client';
import { ConfluenceApiClient } from './confluence-api-client';
import { DataCenterConfluenceApiClient } from './data-center-api-client';

@Injectable()
export class ConfluenceApiClientFactory {
  public constructor(private readonly serviceRegistry: ServiceRegistry) {}

  public create(config: ConfluenceConfig): ConfluenceApiClient {
    const confluenceAuth = this.serviceRegistry.getService(ConfluenceAuth);
    const logger = this.serviceRegistry.getServiceLogger(ConfluenceApiClient);
    return config.instanceType === 'cloud'
      ? new CloudConfluenceApiClient(config, confluenceAuth, logger)
      : new DataCenterConfluenceApiClient(config, confluenceAuth, logger);
  }
}
