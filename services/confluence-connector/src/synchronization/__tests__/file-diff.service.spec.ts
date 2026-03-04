import type { UniqueApiClient } from '@unique-ag/unique-api';
import { describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../../config';
import { ContentType } from '../../confluence-api/types/confluence-api.types';
import { CONFLUENCE_BASE_URL } from '../__mocks__/sync.fixtures';
import { FileDiffService } from '../file-diff.service';
import type { DiscoveredPage } from '../sync.types';

const TENANT_NAME = 'test-tenant';

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

function makeService(performFileDiffImpl: UniqueApiClient['ingestion']['performFileDiff']): {
  service: FileDiffService;
  performFileDiff: ReturnType<typeof vi.fn>;
} {
  const performFileDiff = vi.fn(performFileDiffImpl);
  const uniqueApiClient = {
    ingestion: { performFileDiff },
  } as unknown as UniqueApiClient;

  const confluenceConfig = {
    instanceType: 'cloud',
    baseUrl: CONFLUENCE_BASE_URL,
  } as unknown as ConfluenceConfig;

  return {
    service: new FileDiffService(confluenceConfig, TENANT_NAME, false, uniqueApiClient),
    performFileDiff,
  };
}

describe('FileDiffService', () => {
  it('transforms pages and calls performFileDiff with expected params', async () => {
    const { service, performFileDiff } = makeService(async () => ({
      newFiles: ['SP/p-1'],
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
      `${TENANT_NAME}/space-1_SP`,
      'ATLASSIAN_CONFLUENCE_CLOUD',
      CONFLUENCE_BASE_URL,
    );
    expect(result).toEqual({
      newPageIds: ['SP/p-1'],
      updatedPageIds: [],
      deletedPageIds: [],
      movedPageIds: [],
      deletedKeys: [],
    });
  });

  it('returns categorized ids and deleted keys from file diff response', async () => {
    const { service } = makeService(async () => ({
      newFiles: ['SP/p-1', 'SP/p-1_file.pdf'],
      updatedFiles: ['SP/p-2'],
      deletedFiles: ['SP/p-3', 'SP/p-3_old.pdf'],
      movedFiles: ['SP/p-4', 'SP/p-4_new.pdf'],
    }));

    const result = await service.computeDiff([{ ...basePage }, { ...basePage, id: 'p-2' }]);

    expect(result).toEqual({
      newPageIds: ['SP/p-1', 'SP/p-1_file.pdf'],
      updatedPageIds: ['SP/p-2'],
      deletedPageIds: ['SP/p-3', 'SP/p-3_old.pdf'],
      movedPageIds: ['SP/p-4', 'SP/p-4_new.pdf'],
      deletedKeys: [],
    });
  });

  it('aborts when file diff indicates accidental full deletion', async () => {
    const { service } = makeService(async () => ({
      newFiles: [],
      updatedFiles: [],
      deletedFiles: ['SP/p-1'],
      movedFiles: [],
    }));

    await expect(service.computeDiff([basePage])).rejects.toThrow(
      'File diff would delete 1 files with zero new or updated items. Aborting sync.',
    );
  });
});
