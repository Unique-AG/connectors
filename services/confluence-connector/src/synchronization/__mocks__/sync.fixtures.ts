import { ContentType } from '../../confluence-api';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import type { DiscoveredPage, FetchedPage } from '../sync.types';

export const CONFLUENCE_BASE_URL = 'https://confluence.example.com';

export const discoveredPagesFixture: DiscoveredPage[] = [
  {
    id: '1',
    title: 'Page 1',
    type: ContentType.PAGE,
    spaceId: 'space-1',
    spaceKey: 'SP',
    spaceName: 'Space',
    versionTimestamp: '2026-02-01T00:00:00.000Z',
    webUrl: `${CONFLUENCE_BASE_URL}/page/1`,
    labels: ['ai-ingest'],
  },
];

export const fetchedPagesFixture: FetchedPage[] = [
  {
    id: '1',
    title: 'Page 1',
    body: '<p>content</p>',
    webUrl: `${CONFLUENCE_BASE_URL}/page/1`,
    spaceId: 'space-1',
    spaceKey: 'SP',
    spaceName: 'Space',
    metadata: { confluenceLabels: ['engineering'] },
  },
];

export function createMockTenant(
  name: string,
  overrides: Partial<TenantContext> = {},
): TenantContext {
  return {
    name,
    config: {
      confluence: { baseUrl: CONFLUENCE_BASE_URL },
      processing: { scanIntervalCron: '*/5 * * * *', concurrency: 2 },
      ingestion: {},
    },
    isScanning: false,
    ...overrides,
  } as unknown as TenantContext;
}
