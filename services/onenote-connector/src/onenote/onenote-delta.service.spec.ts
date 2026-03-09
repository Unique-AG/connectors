import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OneNoteDeltaService } from './onenote-delta.service';
import { OneNoteGraphService } from './onenote-graph.service';

describe('OneNoteDeltaService', () => {
  const mockDrizzle = {
    query: {
      deltaState: {
        findFirst: vi.fn(),
      },
    },
    insert: vi.fn().mockReturnValue({
      values: vi.fn().mockReturnValue({
        onConflictDoUpdate: vi.fn(),
      }),
    }),
    delete: vi.fn().mockReturnValue({
      where: vi.fn(),
    }),
  };

  const mockGraphService = {
    getDelta: vi.fn(),
  } as unknown as OneNoteGraphService;

  const mockClient = {} as never;

  let service: OneNoteDeltaService;

  beforeEach(() => {
    vi.clearAllMocks();
    // biome-ignore lint/suspicious/noExplicitAny: Test mock
    service = new OneNoteDeltaService(mockDrizzle as any, mockGraphService);
  });

  describe('fetchDelta', () => {
    it('performs full sync when no existing delta state', async () => {
      mockDrizzle.query.deltaState.findFirst.mockResolvedValue(null);
      (mockGraphService.getDelta as ReturnType<typeof vi.fn>).mockResolvedValue({
        items: [
          { id: 'item-1', package: { type: 'oneNote' }, name: 'My Notebook' },
          { id: 'item-2', name: 'regular-file.docx' },
        ],
        nextDeltaLink: 'https://graph.microsoft.com/delta?token=abc',
      });

      const result = await service.fetchDelta(mockClient, 'user-1');

      expect(result.isFullSync).toBe(true);
      expect(result.changedNotebookNames.has('My Notebook')).toBe(true);
      expect(result.changedNotebookNames.has('regular-file.docx')).toBe(false);
      expect(mockGraphService.getDelta).toHaveBeenCalledWith(mockClient, undefined);
    });

    it('performs incremental sync when delta state exists', async () => {
      mockDrizzle.query.deltaState.findFirst.mockResolvedValue({
        deltaLink: 'https://graph.microsoft.com/delta?token=existing',
      });
      (mockGraphService.getDelta as ReturnType<typeof vi.fn>).mockResolvedValue({
        items: [{ id: 'changed-nb', package: { type: 'oneNote' }, name: 'Changed Notebook' }],
        nextDeltaLink: 'https://graph.microsoft.com/delta?token=new',
      });

      const result = await service.fetchDelta(mockClient, 'user-1');

      expect(result.isFullSync).toBe(false);
      expect(result.changedNotebookNames.has('Changed Notebook')).toBe(true);
      expect(mockGraphService.getDelta).toHaveBeenCalledWith(
        mockClient,
        'https://graph.microsoft.com/delta?token=existing',
      );
    });

    it('falls back to full sync on 410 Gone error', async () => {
      mockDrizzle.query.deltaState.findFirst.mockResolvedValue({
        deltaLink: 'https://graph.microsoft.com/delta?token=expired',
      });
      (mockGraphService.getDelta as ReturnType<typeof vi.fn>)
        .mockRejectedValueOnce(new Error('410 Gone'))
        .mockResolvedValueOnce({
          items: [
            {
              id: 'nb-1',
              name: 'test.onetoc2',
              parentReference: { name: 'Work Notebook' },
            },
          ],
          nextDeltaLink: 'https://graph.microsoft.com/delta?token=fresh',
        });

      const result = await service.fetchDelta(mockClient, 'user-1');

      expect(result.isFullSync).toBe(true);
      expect(result.changedNotebookNames.has('Work Notebook')).toBe(true);
      expect(mockGraphService.getDelta).toHaveBeenCalledTimes(2);
    });

    it('filters .one files and resolves parent notebook names', async () => {
      mockDrizzle.query.deltaState.findFirst.mockResolvedValue(null);
      (mockGraphService.getDelta as ReturnType<typeof vi.fn>).mockResolvedValue({
        items: [
          { id: 'section-1', name: 'Section.one', parentReference: { name: 'Study Notes' } },
          { id: 'doc-1', name: 'Document.docx' },
          { id: 'nb-1', package: { type: 'oneNote' }, name: 'Work Notebook' },
        ],
        nextDeltaLink: 'delta-link',
      });

      const result = await service.fetchDelta(mockClient, 'user-1');

      expect(result.changedNotebookNames.has('Study Notes')).toBe(true);
      expect(result.changedNotebookNames.has('Work Notebook')).toBe(true);
      expect(result.changedNotebookNames.has('Document.docx')).toBe(false);
    });
  });

  describe('clearDelta', () => {
    it('deletes delta state for user', async () => {
      await service.clearDelta('user-1');

      expect(mockDrizzle.delete).toHaveBeenCalled();
    });
  });

  describe('getDeltaStatus', () => {
    it('returns delta state for user', async () => {
      const mockState = {
        userProfileId: 'user-1',
        deltaLink: 'link',
        lastSyncedAt: new Date(),
        lastSyncStatus: 'success',
      };
      mockDrizzle.query.deltaState.findFirst.mockResolvedValue(mockState);

      const result = await service.getDeltaStatus('user-1');

      expect(result).toEqual(mockState);
    });

    it('returns undefined when no state exists', async () => {
      mockDrizzle.query.deltaState.findFirst.mockResolvedValue(undefined);

      const result = await service.getDeltaStatus('user-1');

      expect(result).toBeUndefined();
    });
  });
});
