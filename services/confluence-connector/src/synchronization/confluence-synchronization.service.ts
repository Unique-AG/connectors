import type pino from 'pino';
import type { ServiceRegistry } from '../tenant';
import { getCurrentTenant } from '../tenant/tenant-context.storage';
import { sanitizeError } from '../utils/normalize-error';
import { ConfluenceContentFetcher } from './confluence-content-fetcher';
import { ConfluencePageScanner } from './confluence-page-scanner';

export class ConfluenceSynchronizationService {
  private readonly scanner: ConfluencePageScanner;
  private readonly contentFetcher: ConfluenceContentFetcher;
  private readonly logger: pino.Logger;

  public constructor(serviceRegistry: ServiceRegistry) {
    this.scanner = serviceRegistry.getService(ConfluencePageScanner);
    this.contentFetcher = serviceRegistry.getService(ConfluenceContentFetcher);
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

      const discoveredPages = await this.scanner.discoverPages();
      this.logger.info(
        { count: discoveredPages.length },
        `Discovery completed  ${JSON.stringify(discoveredPages, null, 4)}`,
      );

      // this is for demo purpose only. We will change this once we start implementing ingestion
      const fetchedPages = await this.contentFetcher.fetchPagesContent(discoveredPages);
      this.logger.info(
        { count: fetchedPages.length },
        `Fetching completed ${JSON.stringify(fetchedPages, null, 4)}`,
      );

      this.logger.info('Sync completed');
    } catch (error) {
      this.logger.error({ msg: 'Sync failed', error: sanitizeError(error) });
    } finally {
      tenant.isScanning = false;
    }
  }
}
