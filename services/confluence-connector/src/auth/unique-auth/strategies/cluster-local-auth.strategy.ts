import { UniqueAuthMode, type UniqueConfig } from '../../../config/unique.schema';
import { UniqueAuthAbstract } from '../unique-auth.abstract';

type ClusterLocalConfig = Extract<
  UniqueConfig,
  { serviceAuthMode: typeof UniqueAuthMode.CLUSTER_LOCAL }
>;

const SERVICE_ID_HEADER = 'x-service-id';
const SERVICE_NAME = 'confluence-connector';

export class ClusterLocalAuthStrategy extends UniqueAuthAbstract {
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
