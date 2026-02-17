import { AuthMode } from '../../../config/confluence.schema';
import { ServiceRegistry } from '../../../tenant/service-registry';
import type { Redacted } from '../../../utils/redacted';
import { ConfluenceAuth } from '../confluence-auth.abstract';

interface PatAuthConfig {
  mode: typeof AuthMode.PAT;
  token: Redacted<string>;
}

export class PatAuthStrategy extends ConfluenceAuth {
  private readonly serviceRegistry: ServiceRegistry;
  private readonly token: string;

  public constructor(authConfig: PatAuthConfig, serviceRegistry: ServiceRegistry) {
    super();
    this.serviceRegistry = serviceRegistry;
    this.token = authConfig.token.value;
  }

  public async acquireToken(): Promise<string> {
    const logger = this.serviceRegistry.getServiceLogger(PatAuthStrategy);
    logger.info('Acquiring Confluence PAT token');
    return this.token;
  }
}
