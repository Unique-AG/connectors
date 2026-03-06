import type { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared } from '@unique-ag/utils';
import { describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../../config';
import { ContentType } from '../../confluence-api/types/confluence-api.types';
import { CONFLUENCE_BASE_URL } from '../__mocks__/sync.fixtures';
import { FileDiffService } from '../file-diff.service';
import type { DiscoveredPage } from '../sync.types';

const TENANT_NAME = 'test-tenant';

const basePage: DiscoveredPage = {
  id: 'p-1',
  title: createSmeared('Page 1'),
  type: ContentType.PAGE,
  spaceId: 'space-1',
  spaceKey: 'SP',
  spaceName: 'Space',
  versionTimestamp: '2026-02-01T00:00:00.000Z',
  webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP/pages/1`,
  labels: ['ai-ingest'],
};

const emptyDiffResponse = {
  newFiles: [],
  updatedFiles: [],
  deletedFiles: [],
  movedFiles: [],
};

function makeService(
  performFileDiffImpl: UniqueApiClient['ingestion']['performFileDiff'],
  options?: { useV1KeyFormat?: boolean; instanceType?: 'cloud' | 'data-center' },
): {
  service: FileDiffService;
  performFileDiff: ReturnType<typeof vi.fn>;
} {
  const performFileDiff = vi.fn(performFileDiffImpl);
  const uniqueApiClient = {
    ingestion: { performFileDiff },
  } as unknown as UniqueApiClient;

  const confluenceConfig = {
    instanceType: options?.instanceType ?? 'cloud',
    baseUrl: CONFLUENCE_BASE_URL,
  } as unknown as ConfluenceConfig;

  return {
    service: new FileDiffService(
      confluenceConfig,
      TENANT_NAME,
      options?.useV1KeyFormat ?? false,
      uniqueApiClient,
    ),
    performFileDiff,
  };
}

describe('FileDiffService', () => {
  describe('computeDiff', () => {
    it('returns empty result when no pages are provided', async () => {
      const { service, performFileDiff } = makeService(async () => emptyDiffResponse);

      const result = await service.computeDiff([]);

      expect(performFileDiff).not.toHaveBeenCalled();
      expect(result).toEqual({
        newPageIds: [],
        updatedPageIds: [],
        deletedKeys: [],
        movedPageIds: [],
      });
    });

    it('transforms pages and calls performFileDiff with expected params', async () => {
      const { service, performFileDiff } = makeService(async () => ({
        ...emptyDiffResponse,
        newFiles: ['p-1'],
      }));

      const result = await service.computeDiff([basePage]);

      expect(performFileDiff).toHaveBeenCalledWith(
        [{ key: 'p-1', url: basePage.webUrl, updatedAt: basePage.versionTimestamp }],
        `${TENANT_NAME}/space-1_SP`,
        'ATLASSIAN_CONFLUENCE_CLOUD',
        CONFLUENCE_BASE_URL,
      );
      expect(result).toEqual({
        newPageIds: ['p-1'],
        updatedPageIds: [],
        deletedKeys: [],
        movedPageIds: [],
      });
    });

    it('returns categorized ids from file diff response', async () => {
      const { service } = makeService(async () => ({
        newFiles: ['p-1', 'p-1_file.pdf'],
        updatedFiles: ['p-2'],
        deletedFiles: ['p-3', 'p-3_old.pdf'],
        movedFiles: ['p-4', 'p-4_new.pdf'],
      }));

      const result = await service.computeDiff([
        basePage,
        { ...basePage, id: 'p-2' },
        { ...basePage, id: 'p-3' },
        { ...basePage, id: 'p-4' },
      ]);

      expect(result).toEqual({
        newPageIds: ['p-1', 'p-1_file.pdf'],
        updatedPageIds: ['p-2'],
        deletedKeys: ['p-3', 'p-3_old.pdf'],
        movedPageIds: ['p-4', 'p-4_new.pdf'],
      });
    });

    it('groups pages by space and calls performFileDiff per space', async () => {
      const { service, performFileDiff } = makeService(async () => emptyDiffResponse);

      const pageInSpaceA = { ...basePage, spaceId: 'sa-id', spaceKey: 'SA' };
      const pageInSpaceB = { ...basePage, id: 'p-2', spaceId: 'sb-id', spaceKey: 'SB' };

      await service.computeDiff([pageInSpaceA, pageInSpaceB]);

      expect(performFileDiff).toHaveBeenCalledTimes(2);
      expect(performFileDiff).toHaveBeenCalledWith(
        expect.anything(),
        `${TENANT_NAME}/sa-id_SA`,
        expect.anything(),
        expect.anything(),
      );
      expect(performFileDiff).toHaveBeenCalledWith(
        expect.anything(),
        `${TENANT_NAME}/sb-id_SB`,
        expect.anything(),
        expect.anything(),
      );
    });

    it('aggregates results across multiple spaces', async () => {
      let callCount = 0;
      const { service } = makeService(async () => {
        callCount++;
        if (callCount === 1) {
          return { newFiles: ['p-1'], updatedFiles: [], deletedFiles: ['p-old'], movedFiles: [] };
        }
        return { newFiles: ['p-2'], updatedFiles: ['p-3'], deletedFiles: [], movedFiles: [] };
      });

      const result = await service.computeDiff([
        { ...basePage, spaceKey: 'SA', spaceId: 'sa-id' },
        { ...basePage, id: 'p-2', spaceKey: 'SB', spaceId: 'sb-id' },
        { ...basePage, id: 'p-3', spaceKey: 'SB', spaceId: 'sb-id' },
      ]);

      expect(result).toEqual({
        newPageIds: ['p-1', 'p-2'],
        updatedPageIds: ['p-3'],
        deletedKeys: ['p-old'],
        movedPageIds: [],
      });
    });

    it('uses v1 key format without tenant prefix when useV1KeyFormat is true', async () => {
      const { service, performFileDiff } = makeService(async () => emptyDiffResponse, {
        useV1KeyFormat: true,
      });

      await service.computeDiff([basePage]);

      expect(performFileDiff).toHaveBeenCalledWith(
        expect.anything(),
        'space-1_SP',
        expect.anything(),
        expect.anything(),
      );
    });

    it('uses data-center source kind for data-center instance type', async () => {
      const { service, performFileDiff } = makeService(async () => emptyDiffResponse, {
        instanceType: 'data-center',
      });

      await service.computeDiff([basePage]);

      expect(performFileDiff).toHaveBeenCalledWith(
        expect.anything(),
        expect.anything(),
        'ATLASSIAN_CONFLUENCE_ONPREM',
        expect.anything(),
      );
    });
  });

  describe('accidental deletion guard', () => {
    it('allows deletions when there are new files', async () => {
      const { service } = makeService(async () => ({
        newFiles: ['p-new'],
        updatedFiles: [],
        deletedFiles: ['p-old'],
        movedFiles: [],
      }));

      const result = await service.computeDiff([basePage]);

      expect(result.deletedKeys).toEqual(['p-old']);
    });

    it('allows deletions when there are updated files', async () => {
      const { service } = makeService(async () => ({
        newFiles: [],
        updatedFiles: ['p-1'],
        deletedFiles: ['p-old'],
        movedFiles: [],
      }));

      const result = await service.computeDiff([basePage]);

      expect(result.deletedKeys).toEqual(['p-old']);
    });

    it('aborts when all submitted items would be deleted with no new or updated files', async () => {
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

    it('aborts when more items would be deleted than submitted with no new or updated files', async () => {
      const { service } = makeService(async () => ({
        newFiles: [],
        updatedFiles: [],
        deletedFiles: ['p-1', 'p-1_att.pdf', 'p-orphan'],
        movedFiles: [],
      }));

      await expect(service.computeDiff([basePage])).rejects.toThrow(
        'File diff would delete 3 files with zero new or updated items. Aborting sync.',
      );
    });

    it('allows partial deletion with no new or updated files when fewer items deleted than submitted', async () => {
      const { service } = makeService(async () => ({
        newFiles: [],
        updatedFiles: [],
        deletedFiles: ['p-old'],
        movedFiles: [],
      }));

      const result = await service.computeDiff([basePage, { ...basePage, id: 'p-2' }]);

      expect(result.deletedKeys).toEqual(['p-old']);
    });
  });
});
