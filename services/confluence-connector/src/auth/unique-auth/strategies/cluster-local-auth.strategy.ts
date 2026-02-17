import { UniqueAuthMode, type UniqueConfig } from '../../../config/unique.schema';
import { UniqueAuth } from '../unique-auth.abstract';

type ClusterLocalConfig = Extract<
  UniqueConfig,
  { serviceAuthMode: typeof UniqueAuthMode.CLUSTER_LOCAL }
>;

const SERVICE_ID_HEADER = 'x-service-id';
const SERVICE_NAME = 'confluence-connector';

/*
 * Business logic will be replaced with the shared Unique auth library
 */
export class ClusterLocalAuthStrategy extends UniqueAuth {
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
