import { ConfluenceAuth } from '../auth/confluence-auth';
import { ServiceRegistry } from '../tenant';
import { getCurrentTenant } from '../tenant/tenant-context.storage';
import { smear } from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';

export class ConfluenceSynchronizationService {
  public constructor(private readonly serviceRegistry: ServiceRegistry) {}

  public async synchronize(): Promise<void> {
    const tenant = getCurrentTenant();
    const logger = this.serviceRegistry.getServiceLogger(ConfluenceSynchronizationService);

    if (tenant.isScanning) {
      logger.info('Sync already in progress, skipping');
      return;
    }

    tenant.isScanning = true;
    try {
      logger.info('Starting sync');
      const token = await this.serviceRegistry.getService(ConfluenceAuth).acquireToken();
      logger.info({ token: smear(token) }, 'Token acquired');
      logger.info('Sync completed');
    } catch (error) {
      logger.error({ msg: 'Sync failed', error: sanitizeError(error) });
    } finally {
      tenant.isScanning = false;
    }
  }
}
