import type { UniqueApiClient } from '@unique-ag/unique-api';
import { Smeared } from '@unique-ag/utils';
import { describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../../config';
import { ContentType } from '../../confluence-api/types/confluence-api.types';
import { CONFLUENCE_BASE_URL } from '../__mocks__/sync.fixtures';
import { FileDiffService } from '../file-diff.service';
import type { DiscoveredPage } from '../sync.types';

const TENANT_NAME = 'test-tenant';

const basePage: DiscoveredPage = {
  id: 'p-1',
  title: new Smeared('Page 1', false),
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
  options?: {
    useV1KeyFormat?: boolean;
    instanceType?: 'cloud' | 'data-center';
    totalFilesInUnique?: number;
  },
): {
  service: FileDiffService;
  performFileDiff: ReturnType<typeof vi.fn>;
  getCountByKeyPrefix: ReturnType<typeof vi.fn>;
} {
  const performFileDiff = vi.fn(performFileDiffImpl);
  const getCountByKeyPrefix = vi.fn().mockResolvedValue(options?.totalFilesInUnique ?? 0);
  const uniqueApiClient = {
    ingestion: { performFileDiff },
    files: { getCountByKeyPrefix },
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
    getCountByKeyPrefix,
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
        deletedPageIds: [],
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
        deletedPageIds: [],
        movedPageIds: [],
      });
    });

    it('returns categorized ids from file diff response', async () => {
      const { service } = makeService(
        async () => ({
          newFiles: ['p-1', 'p-1_file.pdf'],
          updatedFiles: ['p-2'],
          deletedFiles: ['p-3', 'p-3_old.pdf'],
          movedFiles: ['p-4', 'p-4_new.pdf'],
        }),
        { totalFilesInUnique: 10 },
      );

      const result = await service.computeDiff([
        basePage,
        { ...basePage, id: 'p-2' },
        { ...basePage, id: 'p-3' },
        { ...basePage, id: 'p-4' },
      ]);

      expect(result).toEqual({
        newPageIds: ['p-1', 'p-1_file.pdf'],
        updatedPageIds: ['p-2'],
        deletedPageIds: ['p-3', 'p-3_old.pdf'],
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
      const { service } = makeService(
        async () => {
          callCount++;
          if (callCount === 1) {
            return { newFiles: ['p-1'], updatedFiles: [], deletedFiles: ['p-old'], movedFiles: [] };
          }
          return { newFiles: ['p-2'], updatedFiles: ['p-3'], deletedFiles: [], movedFiles: [] };
        },
        // Space A has 5 total files → deleting 1 is not full deletion
        { totalFilesInUnique: 5 },
      );

      const result = await service.computeDiff([
        { ...basePage, spaceKey: 'SA', spaceId: 'sa-id' },
        { ...basePage, id: 'p-2', spaceKey: 'SB', spaceId: 'sb-id' },
        { ...basePage, id: 'p-3', spaceKey: 'SB', spaceId: 'sb-id' },
      ]);

      expect(result).toEqual({
        newPageIds: ['p-1', 'p-2'],
        updatedPageIds: ['p-3'],
        deletedPageIds: ['p-old'],
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
    // The guard prevents accidental full deletion of all files for a space.
    // It has two checks:
    //   1. If zero items were submitted and there are deletions → abort (discovery probably failed)
    //   2. If deletedFiles === totalFilesInUnique → abort (would delete everything stored in Unique)

    describe('when deletions should be ALLOWED', () => {
      it('should allow deletions when all submitted pages are unchanged (labels removed from other pages)', async () => {
        // Previously 6 files in Unique. User removed labels from 3 pages, 3 remain.
        // Deleting 3 out of 6 → not full deletion → allowed
        const { service } = makeService(
          async () => ({
            newFiles: [],
            updatedFiles: [],
            deletedFiles: ['p-old-1', 'p-old-2', 'p-old-3'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 6 },
        );

        const result = await service.computeDiff([
          basePage,
          { ...basePage, id: 'p-2' },
          { ...basePage, id: 'p-3' },
        ]);

        expect(result.deletedPageIds).toEqual(['p-old-1', 'p-old-2', 'p-old-3']);
      });

      it('should allow deletions when a single recognized page remains (leave-one-file workflow)', async () => {
        // Previously 6 files in Unique. User removed labels from all except one.
        // Deleting 5 out of 6 → not full deletion → allowed
        const { service } = makeService(
          async () => ({
            newFiles: [],
            updatedFiles: [],
            deletedFiles: ['p-old-1', 'p-old-2', 'p-old-3', 'p-old-4', 'p-old-5'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 6 },
        );

        const result = await service.computeDiff([basePage]);

        expect(result.deletedPageIds).toEqual([
          'p-old-1',
          'p-old-2',
          'p-old-3',
          'p-old-4',
          'p-old-5',
        ]);
      });

      it('should allow deletions when submitted page was updated', async () => {
        // 1 page updated + 1 old page deleted out of 5 total → allowed
        const { service } = makeService(
          async () => ({
            newFiles: [],
            updatedFiles: ['p-1'],
            deletedFiles: ['p-old'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 5 },
        );

        const result = await service.computeDiff([basePage]);

        expect(result.deletedPageIds).toEqual(['p-old']);
      });

      it('should allow deletions when there is a mix of new and recognized pages', async () => {
        // 1 new page + 2 recognized pages, 2 deletions out of 10 total → allowed
        const { service } = makeService(
          async () => ({
            newFiles: ['p-3'],
            updatedFiles: [],
            deletedFiles: ['p-old-1', 'p-old-2'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 10 },
        );

        const result = await service.computeDiff([
          basePage,
          { ...basePage, id: 'p-2' },
          { ...basePage, id: 'p-3' },
        ]);

        expect(result.deletedPageIds).toEqual(['p-old-1', 'p-old-2']);
      });

      it('should allow deletions when submitted page has a moved URL', async () => {
        // Page URL changed + 1 deletion out of 5 total → allowed
        const { service } = makeService(
          async () => ({
            newFiles: [],
            updatedFiles: [],
            deletedFiles: ['p-old'],
            movedFiles: ['p-1'],
          }),
          { totalFilesInUnique: 5 },
        );

        const result = await service.computeDiff([basePage]);

        expect(result.deletedPageIds).toEqual(['p-old']);
      });

      it('should not trigger when there are no deletions', async () => {
        // All pages are new, no deletions → guard irrelevant
        const { service, getCountByKeyPrefix } = makeService(async () => ({
          newFiles: ['p-1', 'p-2'],
          updatedFiles: [],
          deletedFiles: [],
          movedFiles: [],
        }));

        const result = await service.computeDiff([basePage, { ...basePage, id: 'p-2' }]);

        expect(result.deletedPageIds).toEqual([]);
        expect(getCountByKeyPrefix).not.toHaveBeenCalled();
      });

      it('should allow deletions when more items are deleted than submitted but not all', async () => {
        // 1 submitted, 10 deleted out of 20 total → partial deletion → allowed
        const { service } = makeService(
          async () => ({
            newFiles: [],
            updatedFiles: [],
            deletedFiles: [
              'p-old-1',
              'p-old-2',
              'p-old-3',
              'p-old-4',
              'p-old-5',
              'p-old-6',
              'p-old-7',
              'p-old-8',
              'p-old-9',
              'p-old-10',
            ],
            movedFiles: [],
          }),
          { totalFilesInUnique: 20 },
        );

        const result = await service.computeDiff([basePage]);

        expect(result.deletedPageIds).toHaveLength(10);
      });

      it('should allow deletions when all submitted items are new but deletion is not full', async () => {
        // All submitted are new + 1 deletion out of 5 total → partial → allowed
        const { service } = makeService(
          async () => ({
            newFiles: ['p-1'],
            updatedFiles: [],
            deletedFiles: ['p-old'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 5 },
        );

        const result = await service.computeDiff([basePage]);

        expect(result.deletedPageIds).toEqual(['p-old']);
      });

      it('allows when all files are deleted but new files with different IDs are being added', async () => {
        // 2 submitted, 1 deleted = totalFilesInUnique, but new files have different IDs → allowed
        const { service } = makeService(
          async () => ({
            newFiles: ['p-1', 'p-2'],
            updatedFiles: [],
            deletedFiles: ['p-old-1'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 1 },
        );

        const result = await service.computeDiff([basePage, { ...basePage, id: 'p-2' }]);

        expect(result.deletedPageIds).toEqual(['p-old-1']);
      });
    });

    describe('when deletions should be BLOCKED', () => {
      it('should abort when zero items are submitted and there are deletions', async () => {
        // Discovery returned 0 pages but API has files → probably a discovery bug
        const { service } = makeService(async () => ({
          newFiles: [],
          updatedFiles: [],
          deletedFiles: ['p-old-1', 'p-old-2'],
          movedFiles: [],
        }));

        // This case is unreachable via computeDiff (loop doesn't iterate for 0 pages),
        // but validates the guard logic directly
        await expect(
          // @ts-expect-error -- calling private method for testing
          service.validateNoAccidentalFullDeletion(
            [],
            {
              newFiles: [],
              updatedFiles: [],
              deletedFiles: ['p-old-1', 'p-old-2'],
              movedFiles: [],
            },
            'test-tenant/space-1_SP',
          ),
        ).rejects.toThrow(
          'Submitted 0 items to file diff but 2 files would be deleted. Aborting sync.',
        );
      });

      it('should abort when file diff would delete all files stored in Unique', async () => {
        // 3 submitted, 3 deleted, and those 3 are ALL files in Unique for this space
        const { service } = makeService(
          async () => ({
            newFiles: [],
            updatedFiles: [],
            deletedFiles: ['p-old-1', 'p-old-2', 'p-old-3'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 3 },
        );

        await expect(service.computeDiff([basePage])).rejects.toThrow(
          'File diff would delete all 3 files stored in Unique for partialKey',
        );
      });

      it('should abort when key format changed causing full replacement', async () => {
        // All submitted are new (keys changed) + all old files deleted = totalFilesInUnique
        const { service } = makeService(
          async () => ({
            newFiles: ['p-1', 'p-2', 'p-3'],
            updatedFiles: [],
            deletedFiles: ['p-1', 'p-2', 'p-3'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 3 },
        );

        await expect(
          service.computeDiff([basePage, { ...basePage, id: 'p-2' }, { ...basePage, id: 'p-3' }]),
        ).rejects.toThrow('File diff would delete all 3 files stored in Unique for partialKey');
      });

      it('should abort when single file in Unique would be deleted', async () => {
        // Only 1 file in Unique and it would be deleted
        const { service } = makeService(
          async () => ({
            newFiles: [],
            updatedFiles: [],
            deletedFiles: ['p-old'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 1 },
        );

        await expect(service.computeDiff([basePage])).rejects.toThrow(
          'File diff would delete all 1 files stored in Unique for partialKey',
        );
      });

      it('aborts when all files are deleted and new files share IDs with deleted keys (key format bug)', async () => {
        // 2 submitted as new, but deleted keys overlap with submitted keys → key format bug
        const { service } = makeService(
          async () => ({
            newFiles: ['p-1', 'p-2'],
            updatedFiles: [],
            deletedFiles: ['p-1', 'p-2'],
            movedFiles: [],
          }),
          { totalFilesInUnique: 2 },
        );

        await expect(service.computeDiff([basePage, { ...basePage, id: 'p-2' }])).rejects.toThrow(
          'File diff would delete all 2 files stored in Unique for partialKey',
        );
      });
    });
  });
});
