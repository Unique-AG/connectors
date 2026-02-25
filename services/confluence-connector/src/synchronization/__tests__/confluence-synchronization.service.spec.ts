import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ContentType } from '../../confluence-api';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import type { ConfluenceContentFetcher } from '../confluence-content-fetcher';
import type { ConfluencePageScanner } from '../confluence-page-scanner';
import { ConfluenceSynchronizationService } from '../confluence-synchronization.service';
import type { DiscoveredPage, FetchedPage } from '../sync.types';

const mockTenantLogger = vi.hoisted(() => ({
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

const discoveredPagesFixture: DiscoveredPage[] = [
  {
    id: '1',
    title: 'Page 1',
    type: ContentType.PAGE,
    spaceId: 'space-1',
    spaceKey: 'SP',
    spaceName: 'Space',
    versionTimestamp: '2026-02-01T00:00:00.000Z',
    webUrl: 'https://confluence.example.com/page/1',
    labels: ['ai-ingest'],
  },
];

const fetchedPagesFixture: FetchedPage[] = [
  {
    id: '1',
    title: 'Page 1',
    body: '<p>content</p>',
    webUrl: 'https://confluence.example.com/page/1',
    spaceId: 'space-1',
    spaceKey: 'SP',
    spaceName: 'Space',
    metadata: { confluenceLabels: ['engineering'] },
  },
];

function createMockTenant(name: string, overrides: Partial<TenantContext> = {}): TenantContext {
  return {
    name,
    config: {
      processing: { scanIntervalCron: '*/5 * * * *' },
    },
    isScanning: false,
    ...overrides,
  } as unknown as TenantContext;
}

function createService(
  scanner: Pick<ConfluencePageScanner, 'discoverPages'>,
  contentFetcher: Pick<ConfluenceContentFetcher, 'fetchPagesContent'>,
): ConfluenceSynchronizationService {
  return new ConfluenceSynchronizationService(
    scanner as ConfluencePageScanner,
    contentFetcher as ConfluenceContentFetcher,
    mockTenantLogger as never,
  );
}

describe('ConfluenceSynchronizationService', () => {
  let tenant: TenantContext;
  let mockScanner: Pick<ConfluencePageScanner, 'discoverPages'>;
  let mockContentFetcher: Pick<ConfluenceContentFetcher, 'fetchPagesContent'>;
  let service: ConfluenceSynchronizationService;

  beforeEach(() => {
    vi.clearAllMocks();
    tenant = createMockTenant('test-tenant');
    mockScanner = {
      discoverPages: vi.fn().mockResolvedValue(discoveredPagesFixture),
    };
    mockContentFetcher = {
      fetchPagesContent: vi.fn().mockResolvedValue(fetchedPagesFixture),
    };
    service = createService(mockScanner, mockContentFetcher);
  });

  describe('synchronize', () => {
    it('skips when tenant is already scanning', async () => {
      tenant.isScanning = true;

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Sync already in progress, skipping');
      expect(mockScanner.discoverPages).not.toHaveBeenCalled();
      expect(mockContentFetcher.fetchPagesContent).not.toHaveBeenCalled();
    });

    it('runs scanner then content fetcher and logs summaries', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Starting sync');
      expect(mockScanner.discoverPages).toHaveBeenCalledOnce();
      expect(mockContentFetcher.fetchPagesContent).toHaveBeenCalledWith(discoveredPagesFixture);

      const discoverLog = mockTenantLogger.info.mock.calls.find(
        (call) => typeof call[1] === 'string' && call[1].startsWith('Discovery completed'),
      );
      expect(discoverLog).toBeDefined();
      expect(discoverLog?.[0]).toMatchObject({ count: discoveredPagesFixture.length });
      expect(discoverLog?.[1]).toContain('"id": "1"');

      const fetchLog = mockTenantLogger.info.mock.calls.find(
        (call) => typeof call[1] === 'string' && call[1].startsWith('Fetching completed'),
      );
      expect(fetchLog).toBeDefined();
      expect(fetchLog?.[0]).toMatchObject({ count: fetchedPagesFixture.length });
      expect(fetchLog?.[1]).toContain('"id": "1"');

      expect(mockTenantLogger.info).toHaveBeenCalledWith('Sync completed');
    });

    it('resets isScanning after successful sync', async () => {
      await tenantStorage.run(tenant, () => service.synchronize());
      expect(tenant.isScanning).toBe(false);
    });

    it('resets isScanning and logs errors when scanner fails', async () => {
      vi.mocked(mockScanner.discoverPages).mockRejectedValue(new Error('discovery failure'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
      expect(mockTenantLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.any(Error), msg: 'Sync failed' }),
      );
    });

    it('resets isScanning and logs errors when content fetcher fails', async () => {
      vi.mocked(mockContentFetcher.fetchPagesContent).mockRejectedValue(new Error('fetch failure'));

      await tenantStorage.run(tenant, () => service.synchronize());

      expect(tenant.isScanning).toBe(false);
      expect(mockTenantLogger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.any(Error), msg: 'Sync failed' }),
      );
    });
  });
});
