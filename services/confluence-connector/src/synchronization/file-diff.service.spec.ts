import { describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../config';
import { ContentType } from '../confluence-api/types/confluence-api.types';
import { IngestFiles, IngestionMode } from '../constants/ingestion.constants';
import type { ServiceRegistry } from '../tenant';
import type { UniqueApiClient } from '../unique-api/types/unique-api-client.types';
import { UniqueApiClient as UniqueApiClientToken } from '../unique-api/types/unique-api-client.types';
import { CONFLUENCE_BASE_URL } from './__mocks__/sync.fixtures';
import { FileDiffService } from './file-diff.service';
import type { DiscoveredPage } from './sync.types';

const basePage: DiscoveredPage = {
  id: 'p-1',
  title: 'Page 1',
  type: ContentType.PAGE,
  spaceId: 'space-1',
  spaceKey: 'SP',
  spaceName: 'Space',
  versionTimestamp: '2026-02-01T00:00:00.000Z',
  webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP/pages/1`,
  labels: ['ai-ingest'],
};

function makeService(
  performFileDiffImpl: UniqueApiClient['ingestion']['performFileDiff'],
  ingestionOverrides: Partial<{
    ingestFiles: 'enabled' | 'disabled';
    allowedFileExtensions: string[];
  }> = {},
): {
  service: FileDiffService;
  performFileDiff: ReturnType<typeof vi.fn>;
} {
  const performFileDiff = vi.fn(performFileDiffImpl);
  const uniqueApiClient = {
    ingestion: { performFileDiff },
  } as unknown as UniqueApiClient;

  const serviceRegistry = {
    getService: vi.fn((token: unknown) => {
      if (token === UniqueApiClientToken) return uniqueApiClient;
      throw new Error(`Unexpected token: ${String(token)}`);
    }),
    getServiceLogger: vi.fn().mockReturnValue({
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    }),
  } as unknown as ServiceRegistry;

  const confluenceConfig = {
    instanceType: 'cloud',
    baseUrl: CONFLUENCE_BASE_URL,
  } as unknown as ConfluenceConfig;

  const ingestionConfig = {
    ingestionMode: IngestionMode.Flat,
    scopeId: 'scope-1',
    ingestFiles: ingestionOverrides.ingestFiles ?? IngestFiles.Disabled,
    allowedFileExtensions: ingestionOverrides.allowedFileExtensions ?? ['pdf'],
  };

  return {
    service: new FileDiffService(
      confluenceConfig,
      ingestionConfig as unknown as ConstructorParameters<typeof FileDiffService>[1],
      serviceRegistry,
    ),
    performFileDiff,
  };
}

describe('FileDiffService', () => {
  it('transforms pages and calls performFileDiff with expected params', async () => {
    const { service, performFileDiff } = makeService(async () => ({
      newFiles: ['p-1'],
      updatedFiles: [],
      deletedFiles: [],
      movedFiles: [],
    }));

    const result = await service.computeDiff([basePage]);

    expect(performFileDiff).toHaveBeenCalledWith(
      [
        {
          key: 'p-1',
          url: basePage.webUrl,
          updatedAt: basePage.versionTimestamp,
        },
      ],
      CONFLUENCE_BASE_URL,
      'ATLASSIAN_CONFLUENCE_CLOUD',
      CONFLUENCE_BASE_URL,
    );
    expect(result).toEqual({
      newPageIds: ['p-1'],
      updatedPageIds: [],
      deletedPageIds: [],
      movedPageIds: [],
      deletedKeys: [],
    });
  });

  it('includes linked files when file ingestion is enabled', async () => {
    const { service, performFileDiff } = makeService(
      async () => ({
        newFiles: ['p-1', 'p-1_guide.pdf'],
        updatedFiles: [],
        deletedFiles: [],
        movedFiles: [],
      }),
      { ingestFiles: IngestFiles.Enabled, allowedFileExtensions: ['pdf'] },
    );

    const pageBodies = new Map<string, string>([
      [
        'p-1',
        '<a href="/files/guide.pdf?download=true">PDF</a><a href="https://x/file.txt">TXT</a>',
      ],
    ]);

    await service.computeDiff([basePage], pageBodies);

    expect(performFileDiff).toHaveBeenCalledWith(
      [
        {
          key: 'p-1',
          url: basePage.webUrl,
          updatedAt: basePage.versionTimestamp,
        },
        {
          key: 'p-1_guide.pdf',
          url: `${CONFLUENCE_BASE_URL}/files/guide.pdf?download=true`,
          updatedAt: basePage.versionTimestamp,
        },
      ],
      CONFLUENCE_BASE_URL,
      'ATLASSIAN_CONFLUENCE_CLOUD',
      CONFLUENCE_BASE_URL,
    );
  });

  it('deduplicates repeated file hrefs and strips query/fragment for extension checks', async () => {
    const { service, performFileDiff } = makeService(
      async () => ({
        newFiles: ['p-1', 'p-1_guide.pdf'],
        updatedFiles: [],
        deletedFiles: [],
        movedFiles: [],
      }),
      { ingestFiles: IngestFiles.Enabled, allowedFileExtensions: ['pdf'] },
    );

    const pageBodies = new Map<string, string>([
      [
        'p-1',
        [
          '<a href="/files/guide.pdf?download=true#section">PDF1</a>',
          '<a href="/files/guide.pdf?download=true#section">PDF1 duplicate</a>',
          '<a href="/files/skip.txt?download=true">TXT</a>',
        ].join(''),
      ],
    ]);

    await service.computeDiff([basePage], pageBodies);

    const submittedItems = performFileDiff.mock.calls[0]?.[0] ?? [];
    expect(submittedItems).toHaveLength(2);
    expect(submittedItems).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'p-1' }),
        expect.objectContaining({
          key: 'p-1_guide.pdf',
          url: `${CONFLUENCE_BASE_URL}/files/guide.pdf?download=true#section`,
        }),
      ]),
    );
  });

  it('returns categorized ids and deleted keys from file diff response', async () => {
    const { service } = makeService(async () => ({
      newFiles: ['p-1', 'p-1_file.pdf'],
      updatedFiles: ['p-2'],
      deletedFiles: ['p-3', 'p-3_old.pdf'],
      movedFiles: ['p-4', 'p-4_new.pdf'],
    }));

    const result = await service.computeDiff([{ ...basePage }, { ...basePage, id: 'p-2' }]);

    expect(result).toEqual({
      newPageIds: ['p-1'],
      updatedPageIds: ['p-2'],
      deletedPageIds: ['p-3'],
      movedPageIds: ['p-4'],
      deletedKeys: ['p-3', 'p-3_old.pdf'],
    });
  });

  it('aborts when file diff indicates accidental full deletion', async () => {
    const { service } = makeService(async () => ({
      newFiles: [],
      updatedFiles: [],
      deletedFiles: ['p-1'],
      movedFiles: [],
    }));

    await expect(service.computeDiff([basePage])).rejects.toThrow(
      'File diff would delete 1 files with zero new or updated items. Aborting sync.',
    );
  });
});
