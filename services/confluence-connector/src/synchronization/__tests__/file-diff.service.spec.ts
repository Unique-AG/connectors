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
      const { service } = makeService(async () => {
        callCount++;
        if (callCount === 1) {
          // Space A: 1 recognized item (not new) + 1 deletion
          return { newFiles: [], updatedFiles: [], deletedFiles: ['p-old'], movedFiles: [] };
        }
        return { newFiles: ['p-2'], updatedFiles: ['p-3'], deletedFiles: [], movedFiles: [] };
      });

      const result = await service.computeDiff([
        { ...basePage, spaceKey: 'SA', spaceId: 'sa-id' },
        { ...basePage, id: 'p-2', spaceKey: 'SB', spaceId: 'sb-id' },
        { ...basePage, id: 'p-3', spaceKey: 'SB', spaceId: 'sb-id' },
      ]);

      expect(result).toEqual({
        newPageIds: ['p-2'],
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
    // The guard prevents accidental full deletion of all previously-known files for a space.
    // It checks: remainingKnownFiles = submittedItems - newFiles
    //   - If remainingKnownFiles > 0: at least one recognized item survives → allow
    //   - If remainingKnownFiles <= 0: no recognized items survive → abort

    describe('when deletions should be ALLOWED', () => {
      it('should allow deletions when all submitted pages are unchanged (labels removed from other pages)', async () => {
        // User removed labels from 3 pages, 3 remain labeled and unchanged
        // submitted=3, new=0 → remainingKnown=3
        const { service } = makeService(async () => ({
          newFiles: [],
          updatedFiles: [],
          deletedFiles: ['p-old-1', 'p-old-2', 'p-old-3'],
          movedFiles: [],
        }));

        const result = await service.computeDiff([
          basePage,
          { ...basePage, id: 'p-2' },
          { ...basePage, id: 'p-3' },
        ]);

        expect(result.deletedPageIds).toEqual(['p-old-1', 'p-old-2', 'p-old-3']);
      });

      it('should allow deletions when a single recognized page remains (leave-one-file workflow)', async () => {
        // User removed labels from all pages except one to trigger intentional cleanup
        // submitted=1, new=0 → remainingKnown=1
        const { service } = makeService(async () => ({
          newFiles: [],
          updatedFiles: [],
          deletedFiles: ['p-old-1', 'p-old-2', 'p-old-3', 'p-old-4', 'p-old-5'],
          movedFiles: [],
        }));

        const result = await service.computeDiff([basePage]);

        expect(result.deletedPageIds).toEqual(['p-old-1', 'p-old-2', 'p-old-3', 'p-old-4', 'p-old-5']);
      });

      it('should allow deletions when submitted page was updated', async () => {
        // Page content changed + other pages deleted
        // submitted=1, new=0 (updated ≠ new) → remainingKnown=1
        const { service } = makeService(async () => ({
          newFiles: [],
          updatedFiles: ['p-1'],
          deletedFiles: ['p-old'],
          movedFiles: [],
        }));

        const result = await service.computeDiff([basePage]);

        expect(result.deletedPageIds).toEqual(['p-old']);
      });

      it('should allow deletions when there is a mix of new and recognized pages', async () => {
        // Some pages are new, some are recognized, some old pages deleted
        // submitted=3, new=1 → remainingKnown=2
        const { service } = makeService(async () => ({
          newFiles: ['p-3'],
          updatedFiles: [],
          deletedFiles: ['p-old-1', 'p-old-2'],
          movedFiles: [],
        }));

        const result = await service.computeDiff([
          basePage,
          { ...basePage, id: 'p-2' },
          { ...basePage, id: 'p-3' },
        ]);

        expect(result.deletedPageIds).toEqual(['p-old-1', 'p-old-2']);
      });

      it('should allow deletions when submitted page has a moved URL', async () => {
        // Page URL changed + other pages deleted; moved pages are still recognized
        // submitted=1, new=0 → remainingKnown=1
        const { service } = makeService(async () => ({
          newFiles: [],
          updatedFiles: [],
          deletedFiles: ['p-old'],
          movedFiles: ['p-1'],
        }));

        const result = await service.computeDiff([basePage]);

        expect(result.deletedPageIds).toEqual(['p-old']);
      });

      it('should not trigger when there are no deletions', async () => {
        // All pages are new, no old pages exist → no deletions, guard irrelevant
        // submitted=2, new=2, deleted=0
        const { service } = makeService(async () => ({
          newFiles: ['p-1', 'p-2'],
          updatedFiles: [],
          deletedFiles: [],
          movedFiles: [],
        }));

        const result = await service.computeDiff([
          basePage,
          { ...basePage, id: 'p-2' },
        ]);

        expect(result.deletedPageIds).toEqual([]);
      });

      it('should allow deletions when more items are deleted than submitted', async () => {
        // 1 recognized page remains, many old pages to clean up
        // submitted=1, new=0 → remainingKnown=1
        const { service } = makeService(async () => ({
          newFiles: [],
          updatedFiles: [],
          deletedFiles: ['p-old-1', 'p-old-2', 'p-old-3', 'p-old-4', 'p-old-5', 'p-old-6', 'p-old-7', 'p-old-8', 'p-old-9', 'p-old-10'],
          movedFiles: [],
        }));

        const result = await service.computeDiff([basePage]);

        expect(result.deletedPageIds).toHaveLength(10);
      });
    });

    describe('when deletions should be BLOCKED', () => {
      it('should abort when all submitted items are new and there are deletions (possible key format change)', async () => {
        // API does not recognize any submitted items but has old items to delete
        // submitted=1, new=1 → remainingKnown=0
        const { service } = makeService(async () => ({
          newFiles: ['p-1'],
          updatedFiles: [],
          deletedFiles: ['p-old-1', 'p-old-2'],
          movedFiles: [],
        }));

        await expect(service.computeDiff([basePage])).rejects.toThrow(
          'File diff would delete 2 files with 0 recognized items remaining. Aborting sync to prevent accidental full deletion.',
        );
      });

      it('should abort when multiple submitted items are all new with deletions', async () => {
        // All 3 submitted items are new + old items deleted → total state replacement, suspicious
        // submitted=3, new=3 → remainingKnown=0
        const { service } = makeService(async () => ({
          newFiles: ['p-1', 'p-2', 'p-3'],
          updatedFiles: [],
          deletedFiles: ['p-old-1'],
          movedFiles: [],
        }));

        await expect(
          service.computeDiff([
            basePage,
            { ...basePage, id: 'p-2' },
            { ...basePage, id: 'p-3' },
          ]),
        ).rejects.toThrow(
          'File diff would delete 1 files with 0 recognized items remaining.',
        );
      });

      it('should abort when zero items are submitted and there are deletions (unreachable via computeDiff but validates guard)', async () => {
        // submitted=0, new=0 → remainingKnown=0
        const { service } = makeService(async () => emptyDiffResponse);

        expect(() =>
          // @ts-expect-error -- calling private method for testing
          service.validateNoAccidentalFullDeletion([], {
            newFiles: [],
            updatedFiles: [],
            deletedFiles: ['p-old-1', 'p-old-2'],
            movedFiles: [],
          }),
        ).toThrow(
          'File diff would delete 2 files with 0 recognized items remaining.',
        );
      });

      it('should abort when single new item replaces single old item (1:1 swap, suspicious)', async () => {
        // submitted=1, new=1 → remainingKnown=0
        const { service } = makeService(async () => ({
          newFiles: ['p-1'],
          updatedFiles: [],
          deletedFiles: ['p-old'],
          movedFiles: [],
        }));

        await expect(service.computeDiff([basePage])).rejects.toThrow(
          'File diff would delete 1 files with 0 recognized items remaining.',
        );
      });
    });
  });
});
