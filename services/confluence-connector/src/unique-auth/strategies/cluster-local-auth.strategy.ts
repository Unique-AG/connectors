import type { UniqueConfig } from '../../config/unique.schema';
import { UniqueServiceAuth } from '../unique-service-auth';

type ClusterLocalConfig = Extract<UniqueConfig, { serviceAuthMode: 'cluster_local' }>;

const SERVICE_ID_HEADER = 'x-service-id';
const SERVICE_NAME = 'confluence-connector';

export class ClusterLocalAuthStrategy extends UniqueServiceAuth {
  private readonly headers: Record<string, string>;

  public constructor(config: ClusterLocalConfig) {
    super();
    this.headers = {
      ...config.serviceExtraHeaders,
      [SERVICE_ID_HEADER]: SERVICE_NAME,
    };
  }

  public async getHeaders(): Promise<Record<string, string>> {
    return this.headers;
  }
}
