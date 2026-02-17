import type pino from 'pino';
import { ConfluenceAuth } from '../auth/confluence-auth';
import type { ServiceRegistry } from '../tenant';
import { getCurrentTenant } from '../tenant/tenant-context.storage';
import { smear } from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';

export class ConfluenceSynchronizationService {
  private readonly confluenceAuth: ConfluenceAuth;
  private readonly logger: pino.Logger;

  public constructor(serviceRegistry: ServiceRegistry) {
    this.confluenceAuth = serviceRegistry.getService(ConfluenceAuth);
    this.logger = serviceRegistry.getServiceLogger(ConfluenceSynchronizationService);
  }

  public async synchronize(): Promise<void> {
    const tenant = getCurrentTenant();

    if (tenant.isScanning) {
      this.logger.info('Sync already in progress, skipping');
      return;
    }

    tenant.isScanning = true;
    try {
      this.logger.info('Starting sync');
      const token = await this.confluenceAuth.acquireToken();
      this.logger.info({ token: smear(token) }, 'Token acquired');
      this.logger.info('Sync completed');
    } catch (error) {
      this.logger.error({ msg: 'Sync failed', error: sanitizeError(error) });
    } finally {
      tenant.isScanning = false;
    }
  }
}
