import type { IngestionApiResponse, UniqueApiClient } from '@unique-ag/unique-api';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TenantConfig } from '../../config';
import { CONFLUENCE_BASE_URL } from '../__mocks__/sync.fixtures';
import { IngestionService } from '../ingestion.service';
import type { FetchedPage } from '../sync.types';

const mockLogger = vi.hoisted(() => ({
  log: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

vi.mock('@nestjs/common', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nestjs/common')>();
  return {
    ...actual,
    Logger: vi.fn().mockImplementation(() => mockLogger),
  };
});

const TENANT_NAME = 'test-tenant';

const { mockRequest } = vi.hoisted(() => ({
  mockRequest: vi.fn(),
}));

vi.mock('undici', async (importOriginal) => {
  const actual = await importOriginal<typeof import('undici')>();
  return {
    ...actual,
    request: mockRequest,
  };
});

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
} {
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

  const tenantConfig = {
    confluence: {
      instanceType: 'cloud',
      baseUrl: CONFLUENCE_BASE_URL,
    },
    unique: {
      serviceAuthMode: 'external',
      ingestionServiceBaseUrl: 'http://node-ingestion:8091',
    },
    ingestion: {
      storeInternally: true,
      useV1KeyFormat: false,
    },
  } as unknown as TenantConfig;

  return {
    service: new IngestionService(tenantConfig, TENANT_NAME, uniqueApiClient),
    uniqueApiClient,
  };
}

describe('IngestionService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('registers, uploads, and finalizes page ingestion', async () => {
    const { service, uniqueApiClient } = makeService();
    mockRequest.mockResolvedValueOnce({ statusCode: 201 });

    await service.ingestPage(pageFixture, 'space-scope-1');

    expect(uniqueApiClient.ingestion.registerContent).toHaveBeenCalledWith(
      expect.objectContaining({
        key: `${TENANT_NAME}/space-1_SP/42`,
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
        key: `${TENANT_NAME}/space-1_SP/42`,
        fileUrl: 'https://blob.example.com/read',
      }),
    );
  });

  it('skips page ingestion when body is empty', async () => {
    const { service, uniqueApiClient } = makeService();

    await service.ingestPage({ ...pageFixture, body: '' }, 'space-scope-1');

    expect(uniqueApiClient.ingestion.registerContent).not.toHaveBeenCalled();
    expect(mockLogger.log).toHaveBeenCalledWith({
      pageId: '42',
      title: 'Architecture',
      msg: 'Skipping page with empty body',
    });
  });

  it('logs and skips page ingestion when registration fails', async () => {
    const { service, uniqueApiClient } = makeService();
    vi.mocked(uniqueApiClient.ingestion.registerContent).mockRejectedValue(
      new Error('register failed'),
    );

    await service.ingestPage(pageFixture, 'space-scope-1');

    expect(uniqueApiClient.ingestion.finalizeIngestion).not.toHaveBeenCalled();
    expect(mockLogger.error).toHaveBeenCalledWith(
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

    await service.deleteContentByKeys(['k1', 'k2']);

    expect(uniqueApiClient.files.getByKeys).toHaveBeenCalledWith(['k1', 'k2']);
    expect(uniqueApiClient.files.deleteByIds).toHaveBeenCalledWith(['content-1', 'content-2']);
  });

  it('logs and returns when no content is found for delete keys', async () => {
    const { service, uniqueApiClient } = makeService();
    vi.mocked(uniqueApiClient.files.getByKeys).mockResolvedValue([]);

    await service.deleteContentByKeys(['missing-key']);

    expect(uniqueApiClient.files.deleteByIds).not.toHaveBeenCalled();
    expect(mockLogger.log).toHaveBeenCalledWith({
      keyCount: 1,
      msg: 'No content found for keys, nothing to delete',
    });
  });

  it('logs delete errors and continues', async () => {
    const { service, uniqueApiClient } = makeService();
    vi.mocked(uniqueApiClient.files.getByKeys).mockRejectedValue(new Error('delete failed'));

    await service.deleteContentByKeys(['k1']);

    expect(mockLogger.error).toHaveBeenCalledWith(
      expect.objectContaining({
        contentKeys: ['k1'],
        err: expect.anything(),
        msg: 'Failed to delete content, skipping',
      }),
    );
  });

  it('returns early for empty delete input', async () => {
    const { service, uniqueApiClient } = makeService();

    await service.deleteContentByKeys([]);

    expect(uniqueApiClient.files.getByKeys).not.toHaveBeenCalled();
    expect(uniqueApiClient.files.deleteByIds).not.toHaveBeenCalled();
  });

  it('rewrites writeUrl to in-cluster ingestion endpoint in cluster_local mode', async () => {
    const clusterLocalConfig = {
      confluence: { instanceType: 'cloud', baseUrl: CONFLUENCE_BASE_URL },
      unique: {
        serviceAuthMode: 'cluster_local',
        ingestionServiceBaseUrl: 'http://node-ingestion:8091',
      },
      ingestion: { storeInternally: true, useV1KeyFormat: false },
    } as unknown as TenantConfig;

    const uniqueApiClient = {
      ingestion: {
        registerContent: vi.fn().mockResolvedValue(
          makeRegistrationResponse({
            writeUrl: 'https://gateway.qa.unique.app/ingestion/scoped/upload?key=encrypted-key',
          }),
        ),
        finalizeIngestion: vi.fn().mockResolvedValue({ id: 'id-1' }),
      },
      files: { getByKeys: vi.fn(), deleteByIds: vi.fn() },
    } as unknown as UniqueApiClient;

    const service = new IngestionService(clusterLocalConfig, TENANT_NAME, uniqueApiClient);
    mockRequest.mockResolvedValueOnce({ statusCode: 201 });

    await service.ingestPage(pageFixture, 'space-scope-1');

    expect(mockRequest).toHaveBeenCalledWith(
      'http://node-ingestion:8091/scoped/upload?key=encrypted-key',
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  it('passes writeUrl unchanged in external auth mode', async () => {
    const { service } = makeService();
    mockRequest.mockResolvedValueOnce({ statusCode: 201 });

    await service.ingestPage(pageFixture, 'space-scope-1');

    expect(mockRequest).toHaveBeenCalledWith(
      'https://blob.example.com/write',
      expect.objectContaining({ method: 'PUT' }),
    );
  });
});
