import type pino from 'pino';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../../config';
import type { IngestionApiResponse } from '../../unique-api/types/ingestion.types';
import type { UniqueApiClient } from '../../unique-api/types/unique-api-client.types';
import { CONFLUENCE_BASE_URL } from '../__mocks__/sync.fixtures';
import { IngestionService } from '../ingestion.service';
import type { ScopeManagementService } from '../scope-management.service';
import type { FetchedPage } from '../sync.types';

const TENANT_NAME = 'test-tenant';

const { mockRequest } = vi.hoisted(() => ({
  mockRequest: vi.fn(),
}));

vi.mock('undici', () => ({
  request: mockRequest,
}));

const pageFixture: FetchedPage = {
  id: '42',
  title: 'Architecture',
  body: '<p>Hello</p>',
  webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP/pages/42`,
  spaceId: 'space-1',
  spaceKey: 'SP',
  spaceName: 'Space',
  metadata: { confluenceLabels: ['engineering'] },
};

function makeRegistrationResponse(
  overrides: Partial<IngestionApiResponse> = {},
): IngestionApiResponse {
  return {
    id: 'id-1',
    key: 'key-1',
    byteSize: 1,
    mimeType: 'text/html',
    ownerType: 'SCOPE',
    ownerId: 'scope-1',
    writeUrl: 'https://blob.example.com/write',
    readUrl: 'https://blob.example.com/read',
    createdAt: new Date().toISOString(),
    internallyStoredAt: null,
    source: { kind: 'ATLASSIAN_CONFLUENCE_CLOUD', name: CONFLUENCE_BASE_URL },
    ...overrides,
  };
}

function makeService(): {
  service: IngestionService;
  uniqueApiClient: UniqueApiClient;
  scopeManagementService: ScopeManagementService;
  logger: {
    info: ReturnType<typeof vi.fn>;
    error: ReturnType<typeof vi.fn>;
    debug: ReturnType<typeof vi.fn>;
  };
} {
  const logger = { info: vi.fn(), error: vi.fn(), debug: vi.fn() };
  const uniqueApiClient = {
    ingestion: {
      registerContent: vi.fn().mockResolvedValue(makeRegistrationResponse()),
      finalizeIngestion: vi.fn().mockResolvedValue({ id: 'id-1' }),
    },
    files: {
      getByKeys: vi.fn().mockResolvedValue([]),
      deleteByIds: vi.fn().mockResolvedValue(0),
    },
  } as unknown as UniqueApiClient;

  const confluenceConfig = {
    instanceType: 'cloud',
    baseUrl: CONFLUENCE_BASE_URL,
  } as unknown as ConfluenceConfig;

  const scopeManagementService = {
    ensureSpaceScope: vi.fn().mockResolvedValue('space-scope-1'),
  } as unknown as ScopeManagementService;

  return {
    service: new IngestionService(
      confluenceConfig,
      TENANT_NAME,
      scopeManagementService,
      uniqueApiClient,
      logger as unknown as pino.Logger,
    ),
    uniqueApiClient,
    scopeManagementService,
    logger,
  };
}

describe('IngestionService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('registers, uploads, and finalizes page ingestion', async () => {
    const { service, uniqueApiClient } = makeService();
    mockRequest.mockResolvedValueOnce({ statusCode: 201 });

    await service.ingestPage(pageFixture);

    expect(uniqueApiClient.ingestion.registerContent).toHaveBeenCalledWith(
      expect.objectContaining({
        key: `${TENANT_NAME}/SP/42`,
        title: 'Architecture',
        mimeType: 'text/html',
        scopeId: 'space-scope-1',
        sourceKind: 'ATLASSIAN_CONFLUENCE_CLOUD',
        sourceName: CONFLUENCE_BASE_URL,
        metadata: expect.objectContaining({
          confluenceLabels: ['engineering'],
          spaceKey: 'SP',
          spaceName: 'Space',
        }),
      }),
    );
    expect(mockRequest).toHaveBeenCalledWith(
      'https://blob.example.com/write',
      expect.objectContaining({
        method: 'PUT',
        headers: expect.objectContaining({
          'Content-Type': 'text/html',
          'x-ms-blob-type': 'BlockBlob',
        }),
      }),
    );
    expect(uniqueApiClient.ingestion.finalizeIngestion).toHaveBeenCalledWith(
      expect.objectContaining({
        key: `${TENANT_NAME}/SP/42`,
        fileUrl: 'https://blob.example.com/read',
      }),
    );
  });

  it('skips page ingestion when body is empty', async () => {
    const { service, uniqueApiClient, logger } = makeService();

    await service.ingestPage({ ...pageFixture, body: '' });

    expect(uniqueApiClient.ingestion.registerContent).not.toHaveBeenCalled();
    expect(logger.info).toHaveBeenCalledWith(
      { pageId: '42', title: 'Architecture' },
      'Skipping page with empty body',
    );
  });

  it('logs and skips page ingestion when registration fails', async () => {
    const { service, uniqueApiClient, logger } = makeService();
    vi.mocked(uniqueApiClient.ingestion.registerContent).mockRejectedValue(
      new Error('register failed'),
    );

    await service.ingestPage(pageFixture);

    expect(uniqueApiClient.ingestion.finalizeIngestion).not.toHaveBeenCalled();
    expect(logger.error).toHaveBeenCalledWith(
      expect.objectContaining({
        pageId: '42',
        title: 'Architecture',
        err: expect.anything(),
        msg: 'Failed to ingest page, skipping',
      }),
    );
  });

  it('deletes content by resolving keys to ids first', async () => {
    const { service, uniqueApiClient } = makeService();
    vi.mocked(uniqueApiClient.files.getByKeys).mockResolvedValue([
      {
        id: 'content-1',
      },
      {
        id: 'content-2',
      },
    ] as never);
    vi.mocked(uniqueApiClient.files.deleteByIds).mockResolvedValue(2);

    await service.deleteContent(['k1', 'k2']);

    expect(uniqueApiClient.files.getByKeys).toHaveBeenCalledWith(['k1', 'k2']);
    expect(uniqueApiClient.files.deleteByIds).toHaveBeenCalledWith(['content-1', 'content-2']);
  });

  it('logs and returns when no content is found for delete keys', async () => {
    const { service, uniqueApiClient, logger } = makeService();
    vi.mocked(uniqueApiClient.files.getByKeys).mockResolvedValue([]);

    await service.deleteContent(['missing-key']);

    expect(uniqueApiClient.files.deleteByIds).not.toHaveBeenCalled();
    expect(logger.info).toHaveBeenCalledWith(
      { keyCount: 1 },
      'No content found for keys, nothing to delete',
    );
  });

  it('logs delete errors and continues', async () => {
    const { service, uniqueApiClient, logger } = makeService();
    vi.mocked(uniqueApiClient.files.getByKeys).mockRejectedValue(new Error('delete failed'));

    await service.deleteContent(['k1']);

    expect(logger.error).toHaveBeenCalledWith(
      expect.objectContaining({
        contentKeys: ['k1'],
        err: expect.anything(),
        msg: 'Failed to delete content, skipping',
      }),
    );
  });

  it('returns early for empty delete input', async () => {
    const { service, uniqueApiClient } = makeService();

    await service.deleteContent([]);

    expect(uniqueApiClient.files.getByKeys).not.toHaveBeenCalled();
    expect(uniqueApiClient.files.deleteByIds).not.toHaveBeenCalled();
  });
});
